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
  timeout: 180000, // 3 minutes - scraper operations can take time
  headers: {
    'Content-Type': 'application/json',
  },
});

// ============================================================================
// VIN Decoder Service (NHTSA API via Backend)
// ============================================================================

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

export const autoGenerateEstimate = async (intakeData) => {
  try {
    // UPDATED URL to match new backend prefix
    const response = await api.post('/auto-generate/generate', {
      vin: intakeData.vin,
      serviceRequest: intakeData.serviceRequest,
      customerName: intakeData.customerName,
      customerEmail: intakeData.customerEmail || null,
      customerPhone: intakeData.customerPhone,
      odometer: intakeData.odometer ? parseInt(intakeData.odometer) : null,
      laborRate: intakeData.laborRate ? String(intakeData.laborRate) : "150",
      vendorWeights: intakeData.vendorWeights || null
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

// ============================================================================
// Tekmetric Integration
// ============================================================================

export const pushToTekmetric = async (estimateData) => {
  try {
    const response = await api.post('/tekmetric/push', estimateData);
    return {
      success: true,
      data: response.data,
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || 'Failed to push to Tekmetric',
    };
  }
};

// ============================================================================
// Customer Approval Portal
// ============================================================================

export const generateApprovalLink = async (estimateId, estimateData) => {
  try {
    const response = await api.post('/approval/generate-link', {
      estimate_id: estimateId,
      estimate_data: estimateData
    });
    return {
      success: true,
      data: response.data,
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || 'Failed to generate approval link',
    };
  }
};

export const processApprovalAction = async (token, action, notes = '') => {
  try {
    const response = await api.post(`/approval/action/${token}`, {
      action,
      notes
    });
    return {
      success: true,
      data: response.data,
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || 'Failed to process approval action',
    };
  }
};

export const getApprovalStats = async () => {
  try {
    const response = await api.get('/approval/stats');
    return {
      success: true,
      data: response.data,
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || 'Failed to fetch approval stats',
    };
  }
};

export const updateEstimate = async (estimateId, estimateData) => {
  try {
    const response = await api.put(`/estimates/${estimateId}`, {
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
      error: error.response?.data?.detail || 'Failed to update estimate',
    };
  }
};

export default api;
