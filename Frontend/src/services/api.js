/**
 * API Service - Backend Integration
 * 
 * Centralized service for all backend API calls.
 * Base URL: http://localhost:8000/api/v1
 */

import axios from 'axios';

// Create axios instance with base configuration
const API_BASE_URL = import.meta.env.VITE_API_URL || 'https://backend-production-9f132.up.railway.app/api/v1';

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
// AGENT QUEUE — async auto-generate with progress polling
// ============================================================================

export const submitAutoGenJob = async (intake) => {
  try {
    const response = await api.post('/auto-generate/jobs', {
      vin: intake.vin,
      serviceRequest: intake.serviceRequest,
      customerName: intake.customerName,
      customerEmail: intake.customerEmail || null,
      customerPhone: intake.customerPhone,
      odometer: intake.odometer ? parseInt(intake.odometer) : null,
      laborRate: intake.laborRate ? Number(intake.laborRate) : 150,
      partsMarkup: intake.partsMarkup ? Number(intake.partsMarkup) : 30,
      taxRate: intake.taxRate ? Number(intake.taxRate) : 0.0925,
    });
    return { success: true, data: response.data };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || error.message || 'Failed to submit job',
    };
  }
};

export const getAutoGenJob = async (jobId) => {
  try {
    const response = await api.get(`/auto-generate/jobs/${jobId}`);
    return { success: true, data: response.data };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || error.message || 'Failed to fetch job',
    };
  }
};

/**
 * Poll until job reaches a terminal state (success/failed).
 * onProgress({status, progress, progress_pct}) is called after each poll.
 */
export const pollAutoGenJob = async (jobId, { intervalMs = 2500, timeoutMs = 600000, onProgress } = {}) => {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const r = await getAutoGenJob(jobId);
    if (!r.success) return r;
    const job = r.data;
    if (onProgress) onProgress(job);
    if (job.status === 'success' || job.status === 'failed') return { success: true, data: job };
    await new Promise((res) => setTimeout(res, intervalMs));
  }
  return { success: false, error: 'Polling timed out' };
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

// ============================================================================
// Analytics (Dashboard / Vendors / Reports)
// ============================================================================

export const getDashboardAnalytics = async () => {
  try {
    const response = await api.get('/analytics/dashboard');
    return { success: true, data: response.data };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || error.message || 'Failed to load dashboard',
    };
  }
};

export const getVendorAnalytics = async () => {
  try {
    const response = await api.get('/analytics/vendors');
    return { success: true, data: response.data };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || error.message || 'Failed to load vendor stats',
    };
  }
};

export const getReportAnalytics = async (days = 7) => {
  try {
    const response = await api.get('/analytics/reports', { params: { days } });
    return { success: true, data: response.data };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || error.message || 'Failed to load reports',
    };
  }
};

// ============================================================================
// Shop Settings
// ============================================================================

export const getShopSettings = async () => {
  try {
    const response = await api.get('/settings/');
    return { success: true, data: response.data };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || error.message || 'Failed to load settings',
    };
  }
};

export const updateShopSettings = async (payload) => {
  try {
    const response = await api.put('/settings/', payload);
    return { success: true, data: response.data };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || error.message || 'Failed to save settings',
    };
  }
};

// ============================================================================
// Customers
// ============================================================================

export const getCustomers = async () => {
  try {
    const response = await api.get('/customers/');
    return { success: true, data: response.data };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || error.message || 'Failed to load customers',
    };
  }
};

export default api;
