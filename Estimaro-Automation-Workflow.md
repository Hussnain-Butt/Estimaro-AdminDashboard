# Estimaro Automation Workflow Documentation

## Table of Contents

1. [Overview](#overview)
2. [Complete Automation Flow](#complete-automation-flow)
3. [Step-by-Step Automation Details](#step-by-step-automation-details)
4. [AI Components](#ai-components)
5. [Data Processing](#data-processing)
6. [Vendor Integration Logic](#vendor-integration-logic)
7. [Error Handling & Human Override](#error-handling--human-override)
8. [Technical Architecture](#technical-architecture)

---

## Overview

### What Gets Automated

Estimaro automates the **entire estimation workflow** from first customer contact to final approval:

```
Customer Call/Text → VIN Capture → Labor Lookup → Parts Matching 
→ Vendor Pricing → Estimate Creation → Tekmetric Push → Customer Approval
```

### Time Comparison

| Step | Manual Process | With Estimaro | Time Saved |
|------|---------------|---------------|------------|
| VIN Collection | 1-2 min | 30 sec (AI) | 1 min |
| Labor Lookup | 3-4 min | 10 sec (API) | 3 min |
| Parts Matching | 2-3 min | 15 sec (API) | 2 min |
| Vendor Check | 3-5 min | 20 sec (API) | 4 min |
| Estimate Build | 1-2 min | 10 sec (Auto) | 1 min |
| **TOTAL** | **10-15 min** | **2-5 min** | **8-12 min** |

---

## Complete Automation Flow

### Visual Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    CUSTOMER INITIATES CONTACT                    │
│                    (Call, SMS, or Web Form)                      │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: AI INTAKE                                              │
│  • Voice/text AI answers                                        │
│  • Collects: VIN, customer name, phone, job description         │
│  • Natural language processing                                  │
│  • Confirms details with customer                               │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: VIN DECODING & RECALL CHECK ⚠️ UPDATED                 │
│  • Decode VIN via PartsLink24 (preferred - fewer ambiguities)   │
│  • Validate VIN format (17 characters)                          │
│  • Check NHTSA API for open recalls related to job description  │
│  • If recall found → RED FLAG ticket, refer to dealer           │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: WARRANTY CHECK ⚠️ NEW                                   │
│  • Calculate warranty status using "Math Method":               │
│    - < 3 years + < 36k miles → Likely Bumper-to-Bumper          │
│    - < 5 years + < 60k miles → Likely Powertrain                │
│    - Hyundai/Kia: 10 years / 100k miles                         │
│  • Alert advisor if vehicle likely under factory warranty        │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4: JOB CLASSIFICATION                                     │
│  • AI categorizes repair type (brake, AC, engine, etc.)         │
│  • Maps to standard job codes                                   │
│  • Identifies complexity level                                  │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4: LABOR TIME RETRIEVAL (ALLDATA API)                     │
│  • Query ALLDATA with VIN + job code                            │
│  • Retrieve official labor hours                                │
│  • Get procedure steps & special tools needed                   │
│  • Identify required disassembly work                           │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 5: AUTO ADD-ON DETECTION                                  │
│  • Scan procedure for disassembly keywords                      │
│  • Add gaskets, seals, fluids automatically                     │
│  • Flag items with "reason badges"                              │
│  • Apply shop-specific rules                                    │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 6: OEM PART NUMBER MAPPING (PartsLink24 API)              │
│  • Convert VIN + part description → OEM part numbers            │
│  • Get primary + alternate part numbers                         │
│  • Include cross-reference data                                 │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 7: VENDOR PRICING LOOKUP (Worldpac + SSF APIs)            │
│  • Query each vendor with OEM part numbers                      │
│  • Collect: Brand, Price, Stock status, Warehouse location      │
│  • Calculate distance from shop                                 │
│  • Get delivery/pickup times                                    │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 8: VENDOR SCORING & SELECTION                             │
│  • Calculate composite score per vendor offer                   │
│  • Apply shop-configured weights (Brand/Price/Distance)         │
│  • Rank all offers                                              │
│  • Select Primary (highest score) + Backup (second highest)     │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 10: ESTIMATE CALCULATION ⚠️ UPDATED                        │
│  • Labor: hours × shop labor rate                               │
│  • Parts: vendor cost × markup percentage                       │
│  • Taxes: subtotal × tax rate                                   │
│  • Service Cleaning Kits (no shop fees) - varies by task        │
│  • Total = Labor + Parts + Taxes + Cleaning Kit                 │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 11: PART CONDITION DISCLOSURE ⚠️ NEW (CA BAR Compliance)   │
│  • Scan vendor descriptions for keywords:                       │
│    - REMAN: "Reman", "Rmn", "Rebuilt", "Refurb", "Core Charge" │
│    - NEW: "New", "100% New", "Brand New"                        │
│  • Auto-tag parts as [REMANUFACTURED] or [NEW]                  │
│  • Unknown condition → YELLOW flag for manual selection         │
│  • Print on estimate for customer transparency                  │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 10: ESTIMATE FORMATTING                                   │
│  • Generate line items with descriptions                        │
│  • Add reason badges ("Plenum removed → gasket added")          │
│  • Create customer-friendly notes                               │
│  • Format for Tekmetric compatibility                           │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 11: ADVISOR REVIEW (Human Override Point)                 │
│  • Display in advisor dashboard                                 │
│  • Show confidence score                                        │
│  • Allow edits: labor hours, part selection, vendor choice      │
│  • Advisor approves or modifies                                 │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 12: TEKMETRIC INTEGRATION                                 │
│  • Push estimate to Tekmetric via API                           │
│  • Create repair order (RO)                                     │
│  • Link to customer record                                      │
│  • Generate unique estimate ID                                  │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 13: CUSTOMER NOTIFICATION                                 │
│  • Generate unique approval link                                │
│  • Send SMS/Email with shop branding                            │
│  • "Your estimate from [Shop Name] is ready: [link]"           │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 14: CUSTOMER APPROVAL PORTAL                              │
│  • Customer clicks link (no login required)                     │
│  • View estimate with line items                                │
│  • See brand badges, delivery estimates                         │
│  • Click: Approve & Schedule OR Request Callback                │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 15: OUTCOME TRACKING                                      │
│  • Log approval/decline                                         │
│  • Update Tekmetric RO status                                   │
│  • Notify shop staff                                            │
│  • Add to analytics (approval rate, time to approve, etc.)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Automation Details

### Step 1: AI Intake

**Technology**: Natural Language Processing (NLP) + Voice Recognition

**Process**:
1. Customer calls shop phone number or sends SMS
2. AI system answers with: "Hi, this is [Shop Name]. How can I help you today?"
3. Customer explains problem: "My brakes are squeaking"
4. AI asks: "Can you provide your VIN number?" 
5. Customer reads VIN or AI extracts from photo/text
6. AI confirms: "Got it. So you have a [Year Make Model] and need brake service?"
7. AI collects phone number: "What's the best number to reach you?"
8. AI summarizes: "Perfect. We'll prepare your estimate and send it shortly."

**Data Captured**:
```json
{
  "intake_id": "EST-2025-001234",
  "timestamp": "2025-12-04T14:30:00Z",
  "customer": {
    "name": "John Smith",
    "phone": "+1-925-555-0123",
    "email": "john@email.com"
  },
  "vehicle": {
    "vin": "1HGBH41JXMN109876",
    "description_raw": "My brakes are squeaking"
  },
  "job_description": "brake repair - squeaking noise",
  "confidence_score": 0.92
}
```

**Confidence Triggers**:
- **High (≥90%)**: Auto-proceed to next step
- **Medium (70-89%)**: Flag for quick advisor review
- **Low (<70%)**: Route to human advisor immediately

---

### Step 2: VIN Decoding & Recall Check ⚠️ UPDATED

**Technology**: PartsLink24 VIN Decoder (preferred) + NHTSA Recalls API

**Why PartsLink24 for VIN Decode**:
- ALLDATA often gives multiple part options even with VIN input
- PartsLink24 provides cleaner, unambiguous results
- Better for European vehicles (German Sport's specialty)

**Process**:
1. Validate VIN format (17 characters, correct check digit)
2. Decode VIN via PartsLink24 to extract vehicle details
3. **NEW: Check NHTSA API for open recalls**
4. Compare customer complaint to recall descriptions
5. If match found → **RED FLAG** the ticket

**NHTSA Recall Check API Call**:
```http
GET https://api.nhtsa.gov/recalls/recallsByVehicle?vin=WBADT43452G123456
```

**Recall Check Response**:
```json
{
  "Count": 1,
  "results": [
    {
      "Manufacturer": "BMW of North America, LLC",
      "NHTSACampaignNumber": "21V123",
      "Component": "FUEL SYSTEM, GASOLINE",
      "Summary": "Fuel pump flange may leak...",
      "Consequence": "A fuel leak increases the risk of fire.",
      "Remedy": "Dealers will replace the fuel pump flange..."
    }
  ]
}
```

**Recall Matching Logic**:
```javascript
// Check if customer complaint relates to any recall
const customerComplaint = "fuel smell in car";
const relatedRecall = recalls.find(r => 
  r.Component.toLowerCase().includes('fuel') ||
  r.Summary.toLowerCase().includes('fuel')
);

if (relatedRecall) {
  // RED FLAG - refer to dealer
  flagTicket('RED', `Possible recall: ${relatedRecall.NHTSACampaignNumber}`);
  notifyAdvisor('Stop work - refer customer to dealer for free recall repair');
}
```

**Example Decoded Data**:
```json
{
  "vin": "WBADT43452G123456",
  "decoded": {
    "year": 2002,
    "make": "BMW",
    "model": "3 Series",
    "trim": "325i",
    "engine": "2.5L L6",
    "transmission": "Manual 5-Speed",
    "drive_type": "RWD",
    "body_style": "Sedan 4-Door",
    "country": "Germany"
  },
  "recalls": {
    "has_open_recalls": false,
    "count": 0,
    "matches_complaint": false
  },
  "validation": {
    "valid": true,
    "check_digit_match": true
  }
}
```

---

### Step 3: Warranty Math Check ⚠️ NEW

**Technology**: Simple date/mileage calculation logic

**Why This Matters**:
- If vehicle is likely under warranty, customer can get repair FREE at dealer
- Checking at intake = zero wasted labor
- Builds trust: "We could have charged you, but it's covered"

**Warranty Rules**:
```javascript
function checkWarrantyStatus(vehicle) {
  const currentYear = new Date().getFullYear();
  const vehicleAge = currentYear - vehicle.year;
  const mileage = vehicle.mileage;
  
  const alerts = [];
  
  // Bumper-to-Bumper: Most manufacturers
  if (vehicleAge < 3 && mileage < 36000) {
    alerts.push({
      type: 'WARNING',
      message: 'Vehicle likely under BUMPER-TO-BUMPER warranty',
      action: 'Verify with customer before proceeding'
    });
  }
  
  // Powertrain: Most manufacturers
  if (vehicleAge < 5 && mileage < 60000) {
    alerts.push({
      type: 'INFO',
      message: 'Vehicle may have POWERTRAIN warranty coverage',
      action: 'Check if repair is powertrain-related'
    });
  }
  
  // Hyundai/Kia Exception: 10 years / 100k miles
  if (['HYUNDAI', 'KIA'].includes(vehicle.make.toUpperCase())) {
    if (vehicleAge < 10 && mileage < 100000) {
      alerts.push({
        type: 'WARNING',
        message: 'Hyundai/Kia 10yr/100k powertrain warranty may apply',
        action: 'Verify coverage before proceeding'
      });
    }
  }
  
  return alerts;
}
```

**Example Output**:
```json
{
  "vehicle": {
    "year": 2023,
    "make": "BMW",
    "mileage": 28000
  },
  "warranty_check": {
    "alerts": [
      {
        "type": "WARNING",
        "message": "Vehicle likely under BUMPER-TO-BUMPER warranty",
        "action": "Verify with customer before proceeding"
      }
    ],
    "proceed_with_estimate": true,
    "advisor_notification": "⚠️ 2023 BMW with 28k miles - likely still under factory warranty"
  }
}
```

**Advisor Display**:
```
┌──────────────────────────────────────────────────────────────┐
│  ⚠️ WARRANTY ALERT                                           │
│                                                              │
│  This 2023 BMW 330i with 28,000 miles is likely still       │
│  under factory warranty.                                     │
│                                                              │
│  • Bumper-to-Bumper: 3 years / 36,000 miles                 │
│  • Powertrain: 4 years / 50,000 miles                       │
│                                                              │
│  Consider referring customer to dealer for warranty repair.  │
│                                                              │
│  [ Proceed Anyway ]  [ Refer to Dealer ]                    │
└──────────────────────────────────────────────────────────────┘
```

---

### Step 4: Job Classification

**Technology**: AI Text Classification + Job Code Mapping

**Process**:
1. Analyze customer's description: "brakes are squeaking"
2. Extract keywords: ["brakes", "squeaking", "noise"]
3. Map to job categories using trained model
4. Assign standard job codes

**Job Categories**:
```
- Brake System → BR-001 (Brake Pad Replacement)
- Suspension → SU-001 (Shock Replacement)
- Engine → EN-001 (Oil Change), EN-015 (Spark Plugs)
- Electrical → EL-001 (Battery), EL-012 (Alternator)
- AC System → AC-001 (AC Recharge), AC-008 (Compressor)
- Transmission → TR-001 (Fluid Change)
```

**Output**:
```json
{
  "classified_job": {
    "category": "Brake System",
    "job_code": "BR-001",
    "job_name": "Front Brake Pad Replacement",
    "confidence": 0.94,
    "keywords_matched": ["brakes", "squeaking"]
  }
}
```

---

### Step 4: Labor Time Retrieval

**Technology**: ALLDATA API Integration

**API Call**:
```http
POST /api/v1/labor-time
Headers: {
  "Authorization": "Bearer {API_KEY}",
  "Content-Type": "application/json"
}
Body: {
  "vin": "WBADT43452G123456",
  "job_code": "BR-001",
  "vehicle_year": 2002,
  "vehicle_make": "BMW",
  "vehicle_model": "3 Series"
}
```

**Response**:
```json
{
  "labor_time": {
    "job_name": "Front Brake Pads Replacement",
    "labor_hours": 1.2,
    "difficulty_level": "Moderate",
    "procedure_steps": [
      "1. Lift vehicle and remove wheel",
      "2. Remove caliper mounting bolts",
      "3. Remove old brake pads",
      "4. Compress caliper piston",
      "5. Install new brake pads",
      "6. Reinstall caliper",
      "7. Reinstall wheel and test brakes"
    ],
    "special_tools": ["Caliper piston compressor"],
    "warnings": ["Check rotor thickness before reassembly"],
    "disassembly_required": ["wheel_removal"]
  }
}
```

---

### Step 5: Auto Add-On Detection

**Technology**: Rule Engine + Keyword Matching

**Detection Rules**:
```javascript
const ADD_ON_RULES = {
  plenum_removal: {
    keywords: ["plenum removal", "intake manifold removal"],
    auto_add: ["plenum_gasket", "intake_gasket_set"]
  },
  brake_service: {
    keywords: ["brake pad", "brake service"],
    auto_add: ["brake_cleaner", "anti_seize_compound"]
  },
  coolant_flush: {
    keywords: ["coolant flush", "radiator flush"],
    auto_add: ["coolant_fluid", "radiator_cap"]
  },
  oil_change: {
    keywords: ["oil change", "engine oil"],
    auto_add: ["oil_filter", "drain_plug_gasket"]
  }
}
```

**Process**:
1. Scan procedure steps for trigger keywords
2. Match against add-on rules
3. Add items with reason badges
4. Calculate quantities

**Output**:
```json
{
  "auto_added_items": [
    {
      "part_name": "Brake Cleaner Spray",
      "quantity": 1,
      "reason": "Required for brake pad installation",
      "reason_badge": "Brake service → cleaner added"
    },
    {
      "part_name": "Anti-Seize Compound",
      "quantity": 1,
      "reason": "Standard for caliper hardware",
      "reason_badge": "Brake service → lubricant added"
    }
  ]
}
```

---

### Step 6: OEM Part Number Mapping

**Technology**: PartsLink24 API

**API Call**:
```http
POST /api/v1/parts/search
Body: {
  "vin": "WBADT43452G123456",
  "part_description": "Front Brake Pads",
  "position": "front"
}
```

**Response**:
```json
{
  "parts": [
    {
      "oem_number": "34116761244",
      "description": "Brake Pad Set Front",
      "manufacturer": "BMW OEM",
      "fits_vehicles": ["2002 BMW 3 Series 325i"],
      "notes": "Includes wear sensors",
      "superseded_by": null,
      "alternates": [
        {
          "brand": "Bosch",
          "part_number": "BP1234",
          "quality": "OE Equivalent"
        },
        {
          "brand": "Akebono",
          "part_number": "EUR1234",
          "quality": "Premium"
        }
      ]
    }
  ]
}
```

---

### Step 7: Vendor Pricing Lookup

**Technology**: Multi-Vendor API Integration (Parallel Requests)

**Process Flow**:
```
┌─────────────────┐
│ Part Numbers    │
│ 34116761244     │
└────────┬────────┘
         │
         ├──────────────────┬──────────────────┐
         ▼                  ▼                  ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│ Worldpac API   │  │   SSF API      │  │  Future APIs   │
│ Query          │  │   Query        │  │  (Expansion)   │
└────────┬───────┘  └────────┬───────┘  └────────┬───────┘
         │                   │                   │
         └──────────┬────────┴───────────────────┘
                    ▼
         ┌──────────────────────┐
         │  Aggregate Results   │
         └──────────────────────┘
```

**Worldpac API Call**:
```http
GET /api/v1/pricing?part_number=34116761244&zip_code=94597
Response: {
  "offers": [
    {
      "vendor": "Worldpac",
      "brand": "Bosch",
      "part_number": "BP1234",
      "price": 89.99,
      "stock_status": "In Stock",
      "warehouse": {
        "location": "Oakland, CA",
        "distance_miles": 12,
        "pickup_available": true,
        "delivery_time": "Same day"
      }
    }
  ]
}
```

**SSF API Call**:
```http
GET /api/v1/inventory?oem=34116761244
Response: {
  "parts": [
    {
      "vendor": "SSF",
      "brand": "Akebono",
      "part_number": "EUR1234",
      "price": 94.50,
      "availability": "Available",
      "location": "San Francisco, CA",
      "distance": 25,
      "shipping": "Next day"
    }
  ]
}
```

**Aggregated Data**:
```json
{
  "part_oem": "34116761244",
  "vendor_offers": [
    {
      "vendor_id": "worldpac_001",
      "vendor_name": "Worldpac",
      "brand": "Bosch",
      "brand_tier": "OE Equivalent",
      "price": 89.99,
      "stock": "In Stock",
      "warehouse_distance_miles": 12,
      "delivery_option": "Same Day Pickup",
      "warranty": "2 Year"
    },
    {
      "vendor_id": "ssf_001",
      "vendor_name": "SSF",
      "brand": "Akebono",
      "brand_tier": "Premium",
      "price": 94.50,
      "stock": "Available",
      "warehouse_distance_miles": 25,
      "delivery_option": "Next Day Delivery",
      "warranty": "Lifetime"
    }
  ]
}
```

---

### Step 8: Vendor Scoring & Selection

**Scoring Algorithm**:

```javascript
function calculateVendorScore(offer, weights) {
  // Normalize weights to sum to 100%
  const totalWeight = weights.brand + weights.price + weights.distance;
  const normalized = {
    brand: (weights.brand / totalWeight) * 100,
    price: (weights.price / totalWeight) * 100,
    distance: (weights.distance / totalWeight) * 100
  };
  
  // Brand scoring (0-10 scale)
  const brandScores = {
    'OEM': 10,
    'Premium': 9,
    'OE Equivalent': 8,
    'Standard': 6,
    'Economy': 4
  };
  const brandScore = brandScores[offer.brand_tier] || 5;
  
  // Price scoring (inverse - lower is better, 0-10 scale)
  const maxPrice = Math.max(...allOffers.map(o => o.price));
  const minPrice = Math.min(...allOffers.map(o => o.price));
  const priceScore = 10 - ((offer.price - minPrice) / (maxPrice - minPrice)) * 10;
  
  // Distance scoring (inverse - closer is better, 0-10 scale)
  const maxDistance = 50; // miles
  const distanceScore = Math.max(0, 10 - (offer.warehouse_distance_miles / maxDistance) * 10);
  
  // Calculate weighted composite score
  const compositeScore = (
    (brandScore * normalized.brand) +
    (priceScore * normalized.price) +
    (distanceScore * normalized.distance)
  ) / 10; // Scale to 0-100
  
  return {
    vendor: offer.vendor_name,
    brand: offer.brand,
    price: offer.price,
    distance: offer.warehouse_distance_miles,
    scores: {
      brand: brandScore.toFixed(1),
      price: priceScore.toFixed(1),
      distance: distanceScore.toFixed(1),
      composite: compositeScore.toFixed(1)
    }
  };
}

// Shop-configured weights
const shopWeights = {
  brand: 40,    // 40% weight on brand quality
  price: 35,    // 35% weight on price
  distance: 25  // 25% weight on distance
};

// Score all offers
const scoredOffers = vendorOffers.map(offer => 
  calculateVendorScore(offer, shopWeights)
);

// Sort by composite score descending
scoredOffers.sort((a, b) => b.scores.composite - a.scores.composite);

// Select Primary and Backup
const primary = scoredOffers[0];
const backup = scoredOffers[1];
```

**Example Output**:
```json
{
  "scoring_results": [
    {
      "rank": 1,
      "selection": "Primary",
      "vendor": "Worldpac",
      "brand": "Bosch",
      "price": 89.99,
      "distance_miles": 12,
      "scores": {
        "brand": 8.0,
        "price": 9.5,
        "distance": 7.6,
        "composite": 84.3
      }
    },
    {
      "rank": 2,
      "selection": "Backup",
      "vendor": "SSF",
      "brand": "Akebono",
      "price": 94.50,
      "distance_miles": 25,
      "scores": {
        "brand": 9.0,
        "price": 8.0,
        "distance": 5.0,
        "composite": 74.5
      }
    }
  ]
}
```

---

### Step 9: Estimate Calculation ⚠️ UPDATED

**Calculation Formula**:

```javascript
function calculateEstimate(laborHours, parts, shopSettings, jobType) {
  // Labor calculation
  const laborCost = laborHours * shopSettings.laborRate;
  
  // Parts calculation with markup
  const partsSubtotal = parts.reduce((sum, part) => {
    const vendorCost = part.price * part.quantity;
    const markedUpCost = vendorCost * (1 + shopSettings.partsMarkup);
    return sum + markedUpCost;
  }, 0);
  
  // Subtotal
  const subtotal = laborCost + partsSubtotal;
  
  // Taxes
  const taxAmount = subtotal * shopSettings.taxRate;
  
  // Service Cleaning Kit (replaces shop fees) ⚠️ UPDATED
  const cleaningKit = getCleaningKitForJob(jobType);
  
  // Grand total
  const grandTotal = subtotal + taxAmount + cleaningKit.price;
  
  return {
    labor: {
      hours: laborHours,
      rate: shopSettings.laborRate,
      total: laborCost
    },
    parts: {
      items: parts,
      subtotal: partsSubtotal
    },
    subtotal: subtotal,
    tax: taxAmount,
    cleaning_kit: cleaningKit,  // ⚠️ NEW - replaces fees
    grand_total: grandTotal
  };
}

// Service Cleaning Kit selection based on job type ⚠️ NEW
function getCleaningKitForJob(jobType) {
  const cleaningKits = {
    'brake_service': {
      name: 'Brake Service Cleaning Kit',
      includes: ['Brake cleaner', 'Caliper grease', 'Disposable gloves'],
      price: 15.00
    },
    'engine_repair': {
      name: 'Engine Service Cleaning Kit',
      includes: ['Degreaser', 'Shop towels', 'Oil absorbent'],
      price: 20.00
    },
    'ac_service': {
      name: 'AC Service Cleaning Kit',
      includes: ['UV dye', 'Leak sealant', 'O-ring lubricant'],
      price: 18.00
    },
    'general': {
      name: 'General Service Cleaning Kit',
      includes: ['All-purpose cleaner', 'Shop towels'],
      price: 12.00
    }
  };
  
  return cleaningKits[jobType] || cleaningKits['general'];
}

// Example shop settings (NO SHOP FEES)
const shopSettings = {
  laborRate: 150.00,      // $150 per hour
  partsMarkup: 0.30,      // 30% markup on parts
  taxRate: 0.0925,        // 9.25% CA sales tax
  // shopFee: REMOVED - using cleaning kits instead
};
```

**Estimate Breakdown**:
```json
{
  "estimate_id": "EST-2025-001234",
  "line_items": {
    "labor": {
      "description": "Front Brake Pad Replacement",
      "hours": 1.2,
      "rate_per_hour": 150.00,
      "total": 180.00
    },
    "parts": [
      {
        "part_number": "34116761244",
        "description": "Brake Pad Set - Front (Bosch)",
        "condition": "REMANUFACTURED",
        "vendor_cost": 89.99,
        "markup_percent": 30,
        "customer_price": 116.99,
        "quantity": 1,
        "total": 116.99,
        "reason_badge": null
      },
      {
        "part_number": "BC-100",
        "description": "Brake Cleaner Spray",
        "condition": "NEW",
        "vendor_cost": 8.99,
        "markup_percent": 30,
        "customer_price": 11.69,
        "quantity": 1,
        "total": 11.69,
        "reason_badge": "Brake service → cleaner added"
      }
    ]
  },
  "summary": {
    "labor_total": 180.00,
    "parts_total": 128.68,
    "subtotal": 308.68,
    "tax_rate": 9.25,
    "tax_amount": 28.55,
    "cleaning_kit": {
      "name": "Brake Service Cleaning Kit",
      "price": 15.00
    },
    "grand_total": 352.23
  }
}
```

---

### Step 10: Part Condition Disclosure ⚠️ NEW (CA BAR Compliance)

**Purpose**: Automatically detect and disclose whether parts are NEW or REMANUFACTURED.

**Why This Is Required**:
- California Bureau of Automotive Repair (BAR) requires disclosure
- Failure to disclose can result in fines or license issues
- Manages customer expectations ("I paid for new, not rebuilt")

**Keyword Detection Logic**:

```javascript
function detectPartCondition(partDescription) {
  const description = partDescription.toUpperCase();
  
  // REMANUFACTURED indicators
  const remanKeywords = [
    'REMAN', 'RMN', 'REBUILT', 'REFURB', 'REFURBISHED',
    'CORE CHARGE', 'EXCHANGE', 'RECO', 'RECONDITIONED'
  ];
  
  // NEW indicators
  const newKeywords = [
    '100% NEW', 'BRAND NEW', 'NEW OEM', 'NEW AFTERMARKET'
  ];
  
  // Check for REMAN first (takes priority)
  for (const keyword of remanKeywords) {
    if (description.includes(keyword)) {
      return {
        condition: 'REMANUFACTURED',
        confidence: 'HIGH',
        matched_keyword: keyword,
        display_tag: '[REMANUFACTURED]'
      };
    }
  }
  
  // Check for explicit NEW
  for (const keyword of newKeywords) {
    if (description.includes(keyword)) {
      return {
        condition: 'NEW',
        confidence: 'HIGH',
        matched_keyword: keyword,
        display_tag: '[NEW]'
      };
    }
  }
  
  // If just 'NEW' appears (common case)
  if (description.includes('NEW')) {
    return {
      condition: 'NEW',
      confidence: 'MEDIUM',
      matched_keyword: 'NEW',
      display_tag: '[NEW]'
    };
  }
  
  // Unknown - flag for manual selection
  return {
    condition: 'UNKNOWN',
    confidence: 'LOW',
    matched_keyword: null,
    display_tag: null,
    requires_manual_selection: true,
    flag_color: 'YELLOW'
  };
}

// Example usage
const vendorDescriptions = [
  'BOSCH STARTER - RMN',           // → REMANUFACTURED
  'AKEBONO BRAKE PADS - NEW',      // → NEW
  'NGK SPARK PLUG SET',            // → UNKNOWN (flag)
  'REBUILT ALTERNATOR W/ CORE',    // → REMANUFACTURED
];

vendorDescriptions.forEach(desc => {
  const result = detectPartCondition(desc);
  console.log(`${desc} → ${result.condition}`);
});
```

**Worldpac Description Examples**:
```
W0133-183492 BOSCH STARTER - RMN          → [REMANUFACTURED]
BP1234 AKEBONO BRAKE PADS EUR            → [UNKNOWN] - flag YELLOW
34116761244 BMW OEM PAD SET - NEW        → [NEW]
ALT-5678 REBUILT ALTERNATOR              → [REMANUFACTURED]
```

**Customer Estimate Display**:

```
┌─────────────────────────────────────────────────────────────────┐
│  PARTS                                                          │
├─────────────────────────────────────────────────────────────────┤
│  Starter Motor (Bosch) - [REMANUFACTURED]           $156.99    │
│  Brake Pad Set Front (Akebono) - [NEW]              $116.99    │
│  Spark Plug Set (NGK) - [NEW]                       $ 45.99    │
└─────────────────────────────────────────────────────────────────┘
```

**Advisor Review Screen (Unknown Condition)**:

```
┌──────────────────────────────────────────────────────────────────┐
│  ⚠️ MANUAL SELECTION REQUIRED                                    │
│                                                                  │
│  Part: Alternator (AC Delco)                                     │
│  Vendor Description: "ACD ALTERNATOR 145A"                       │
│                                                                  │
│  System could not determine if this part is New or Reman.        │
│  Please select one:                                              │
│                                                                  │
│  [ NEW ]    [ REMANUFACTURED ]                                   │
│                                                                  │
│  This will be printed on the customer estimate.                  │
└──────────────────────────────────────────────────────────────────┘
```

**Output JSON**:
```json
{
  "part_condition_check": {
    "total_parts": 4,
    "auto_detected": 3,
    "requires_review": 1,
    "parts": [
      {
        "part_number": "ST-12345",
        "description": "Bosch Starter - RMN",
        "detected_condition": "REMANUFACTURED",
        "display_on_estimate": "Starter Motor (Bosch) - **REMANUFACTURED**"
      },
      {
        "part_number": "BP-67890",
        "description": "Akebono Brake Pads",
        "detected_condition": "NEW",
        "display_on_estimate": "Brake Pad Set (Akebono) - **NEW**"
      },
      {
        "part_number": "ALT-11111",
        "description": "ACD Alternator 145A",
        "detected_condition": "UNKNOWN",
        "flag": "YELLOW",
        "advisor_action_required": true,
        "prompt": "Please select: NEW or REMANUFACTURED"
      }
    ]
  }
}
```

---

## AI Components

### 1. Voice AI (Call Handling)

**Technology Stack**:
- Speech-to-Text: Google Cloud Speech-to-Text or AWS Transcribe
- NLP: Custom trained model for automotive domain
- Text-to-Speech: Natural voice synthesis

**Training Data**:
- 10,000+ real shop call recordings
- 500+ common repair scenarios
- VIN extraction patterns
- Appointment scheduling flows

### 2. Text Classification (Job Categorization)

**Model**: Fine-tuned BERT for automotive domain

**Training Dataset**:
```
- 50,000+ repair order descriptions
- 200+ job categories
- Keywords and synonyms database
```

**Accuracy Target**: 95%+ classification accuracy

### 3. Confidence Scoring

**Algorithm**:
```javascript
function calculateConfidenceScore(intake) {
  let score = 100;
  
  // VIN validation
  if (!isValidVIN(intake.vin)) score -= 30;
  
  // Job classification confidence
  if (intake.job_classification_confidence < 0.8) score -= 20;
  
  // Customer info completeness
  if (!intake.customer.phone) score -= 15;
  if (!intake.customer.name) score -= 10;
  
  // Description clarity
  if (intake.description.length < 10) score -= 15;
  
  return Math.max(0, score) / 100;
}
```

**Thresholds**:
- ≥90%: Auto-proceed
- 70-89%: Quick review
- <70%: Human required

---

## Error Handling & Human Override

### Error Scenarios

| Error Type | Detection | Resolution |
|------------|-----------|------------|
| Invalid VIN | Validation fails | Request re-entry |
| Part not found | PartsLink24 returns empty | Flag for manual lookup |
| All vendors out of stock | No availability | Notify advisor, suggest alternatives |
| API timeout | No response in 5s | Retry 3x, then flag |
| Price discrepancy | >20% variation | Flag for review |

### Human Override Points

```
┌──────────────────────────────────────────┐
│         Automation Flow                  │
│                                          │
│  [AI Intake] ←──── Override if low conf │
│      ↓                                   │
│  [Labor Lookup] ←─ Override labor hours │
│      ↓                                   │
│  [Parts Match] ←── Override part select │
│      ↓                                   │
│  [Vendor Score] ←─ Override vendor pick │
│      ↓                                   │
│  [Final Review] ←─ Required checkpoint  │
│      ↓                                   │
│  [Push to Tekmetric]                    │
└──────────────────────────────────────────┘
```

---

## Technical Architecture

### System Components

```
┌─────────────────────────────────────────────────────┐
│              Frontend (React/Vue)                    │
│  - Advisor Dashboard                                │
│  - Customer Approval Portal                         │
└──────────────┬──────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────┐
│         Backend API (Node.js/Python)                │
│  - Request Orchestration                            │
│  - Business Logic                                   │
│  - Caching Layer (Redis)                            │
└──────────────┬──────────────────────────────────────┘
               │
         ┌─────┴─────┐
         │           │
┌────────▼──┐   ┌────▼────────┐
│  AI Layer │   │ Integration │
│  - NLP    │   │   Layer     │
│  - Voice  │   └─────┬───────┘
│  - Score  │         │
└───────────┘    ┌────┴──────────────────┐
                 │                       │
         ┌───────▼──────┐    ┌──────────▼─────┐
         │External APIs │    │  Database      │
         │- Tekmetric   │    │  - Estimates   │
         │- ALLDATA     │    │  - Customers   │
         │- PartsLink24 │    │  - Analytics   │
         │- Worldpac    │    │  - Cache       │
         │- SSF         │    └────────────────┘
         └──────────────┘
```

### Data Flow

```
Customer → AI Intake → Queue → Worker Thread → External APIs
                                      ↓
                              Cache Check First
                                      ↓
                              Format Response
                                      ↓
                              Advisor Dashboard
```

---

**Document Version**: 1.0  
**Last Updated**: December 4, 2025  
**Purpose**: Technical workflow documentation for Estimaro automation system
