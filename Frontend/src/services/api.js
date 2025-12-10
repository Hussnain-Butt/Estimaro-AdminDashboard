/**
 * API Service - Backend Integration
 * 
 * Centralized service for all backend API calls.
 * Base URL: http://localhost:8000/api/v1
 */

import axios from 'axios';

// Create axios instance with base configuration
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000, // Increased timeout for production
  headers: {
    'Content-Type': 'application/json',
  },
});

// ============================================================================
// VIN Decoder Service (NHTSA API via Backend)
// ============================================================================

/**
 * Decode VIN to get vehicle information
 * @param {string} vin - Vehicle Identification Number (17 characters)
 * @returns {Promise<Object>} Vehicle details (year, make, model, trim, engine)
 */
export const decodeVIN = async (vin) => {
  try {
    const response = await api.get(`/vehicles/decode/${vin}`);
    return {
      success: true,
      data: response.data,
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || 'Failed to decode VIN',
    };
  }
};

// ============================================================================
// Labor Time Lookup Service
// ============================================================================

/**
 * Get labor time for a specific job
 * @param {string} vin - Vehicle VIN
 * @param {string} jobDescription - Job description (e.g., "Brake Pad Replacement")
 * @returns {Promise<Object>} Labor time details
 */
export const lookupLaborTime = async (vin, jobDescription) => {
  try {
    const response = await api.post('/labor/lookup', {
      vin,
      jobDescription,
    });
    return {
      success: true,
      data: response.data,
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || 'Failed to lookup labor time',
    };
  }
};

// ============================================================================
// Parts Search Service
// ============================================================================

/**
 * Search for parts based on VIN and job description
 * @param {string} vin - Vehicle VIN
 * @param {string} jobDescription - Job description
 * @returns {Promise<Object>} Array of matching parts
 */
export const searchParts = async (vin, jobDescription) => {
  try {
    const response = await api.post('/parts/search', {
      vin,
      jobDescription,
    });
    return {
      success: true,
      data: response.data,
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || 'Failed to search parts',
    };
  }
};

// ============================================================================
// Estimate Calculation Service
// ============================================================================

/**
 * Calculate estimate totals in real-time
 * @param {Array} laborItems - Array of labor items {description, hours, rate, total}
 * @param {Array} partsItems - Array of parts items {description, quantity, cost, markup, total}
 * @param {number} taxRate - Tax rate (0.08 = 8%)
 * @returns {Promise<Object>} Calculation breakdown
 */
export const calculateEstimate = async (laborItems, partsItems, taxRate = 0.08) => {
  try {
    const response = await api.post('/estimates/calculate', {
      laborItems: laborItems.map(item => ({
        description: item.title || item.description,
        hours: String(item.hours),
        rate: String(item.rate || 150),
        total: String((item.hours * (item.rate || 150)).toFixed(2)),
      })),
      partsItems: partsItems.map(item => ({
        description: item.name || item.description,
        partNumber: item.number || item.partNumber || '',
        quantity: String(item.quantity || 1),
        cost: String(item.price || item.cost || 0),
        markup: String(item.markup || 0),
        total: String(item.price || item.cost || 0),
        vendor: item.source || item.vendor || '',
      })),
      taxRate: String(taxRate),
    });
    return {
      success: true,
      data: response.data,
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || 'Failed to calculate estimate',
    };
  }
};

// ============================================================================
// Draft Estimate Creation Service
// ============================================================================

/**
 * Create a draft estimate
 * @param {Object} estimateData - Complete estimate data
 * @returns {Promise<Object>} Created estimate with ID and public token
 */
export const createDraftEstimate = async (estimateData) => {
  try {
    const response = await api.post('/estimates/draft', {
      vehicleInfo: {
        vin: estimateData.vin,
        year: estimateData.vehicleYear,
        make: estimateData.vehicleMake,
        model: estimateData.vehicleModel,
        trim: estimateData.vehicleTrim,
        engine: estimateData.vehicleEngine,
        mileage: estimateData.odometer ? parseInt(estimateData.odometer) : null,
      },
      customerInfo: {
        firstName: estimateData.customerFirstName || estimateData.customer?.split(' ')[0] || '',
        lastName: estimateData.customerLastName || estimateData.customer?.split(' ').slice(1).join(' ') || '',
        email: estimateData.customerEmail || null,
        phone: estimateData.customerPhone || '',
      },
      serviceRequest: estimateData.serviceRequest || '',
      laborItems: estimateData.laborItems.map(item => ({
        description: item.title || item.description,
        hours: String(item.hours),
        rate: String(item.rate || 150),
        total: String((item.hours * (item.rate || 150)).toFixed(2)),
      })),
      partsItems: estimateData.partsItems.map(item => ({
        description: item.name || item.description,
        partNumber: item.number || item.partNumber || '',
        quantity: String(item.quantity || 1),
        cost: String(item.price || item.cost || 0),
        markup: String(item.markup || 0),
        total: String(item.price || item.cost || 0),
        vendor: item.source || item.vendor || '',
      })),
    });
    return {
      success: true,
      data: response.data,
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || 'Failed to create draft estimate',
    };
  }
};

// ============================================================================
// Get Estimates List
// ============================================================================

/**
 * Get list of estimates with optional status filter
 * @param {string} status - Optional status filter (draft, sent, approved, declined)
 * @returns {Promise<Object>} Array of estimates
 */
export const getEstimates = async (status = null) => {
  try {
    const params = status ? { status_filter: status } : {};
    const response = await api.get('/estimates/', { params });
    return {
      success: true,
      data: response.data,
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || 'Failed to fetch estimates',
    };
  }
};

// ============================================================================
// Send Estimate to Customer
// ============================================================================

/**
 * Send estimate to customer (updates status and sets expiration)
 * @param {number} estimateId - Estimate ID
 * @param {number} daysValid - Days until expiration (default 7)
 * @returns {Promise<Object>} Updated estimate
 */
export const sendEstimate = async (estimateId, daysValid = 7) => {
  try {
    const response = await api.post(`/estimates/${estimateId}/send`, null, {
      params: { days_valid: daysValid },
    });
    return {
      success: true,
      data: response.data,
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || 'Failed to send estimate',
    };
  }
};

// ============================================================================
// 🚀 AUTO-GENERATE ESTIMATE (One-Click Magic!)
// ============================================================================

/**
 * Auto-generate complete estimate from intake information
 * This is the MAIN function that orchestrates the entire workflow:
 * 1. VIN Decode
 * 2. Labor Lookup
 * 3. Parts Search
 * 4. Vendor Compare
 * 5. Calculate Totals
 * 
 * @param {Object} intakeData - Intake information
 * @param {string} intakeData.vin - Vehicle VIN
 * @param {string} intakeData.serviceRequest - Service request description
 * @param {string} intakeData.customerName - Customer name
 * @param {string} intakeData.customerEmail - Customer email
 * @param {string} intakeData.customerPhone - Customer phone
 * @param {number} intakeData.odometer - Odometer reading
 * @param {number} intakeData.laborRate - Shop labor rate
 * @returns {Promise<Object>} Complete estimate with all steps
 */
export const autoGenerateEstimate = async (intakeData) => {
  try {
    const response = await api.post('/auto/generate', {
      vin: intakeData.vin,
      serviceRequest: intakeData.serviceRequest,
      customerName: intakeData.customerName,
      customerEmail: intakeData.customerEmail || null,
      customerPhone: intakeData.customerPhone,
      odometer: intakeData.odometer ? parseInt(intakeData.odometer) : null,
      laborRate: intakeData.laborRate ? String(intakeData.laborRate) : "150",
    });
    return {
      success: true,
      data: response.data,
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || 'Failed to auto-generate estimate',
    };
  }
};

export default api;
