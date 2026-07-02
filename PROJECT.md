# SFC Issue Tickets Dashboard

**Project**: Custom Report for Southern Franchise Company LLC (SFC)  
**Platform**: Taqtics Custom Reports (Pattern C)  
**Status**: Production-ready  
**Last Updated**: 02 June 2026  
**Data Period**: Jan 2026 – May 2026 (1,739+ tickets)

---

## Project Overview

A self-contained, interactive HTML5 dashboard built in Python + Plotly.js that visualizes issue ticket data from the Taqtics platform. The dashboard provides dual views (Count and Overdue) with comprehensive filtering, real-time metrics, and actionable insights across brands, stores, categories, and assignees.

**Why dual dashboards?**
- **Count View**: Monitor overall ticket volume, status distribution, and operational workflow
- **Overdue View**: Focus exclusively on tickets that exceed SLA or are past due, prioritizing urgent work

---

## Technical Stack

| Component | Technology |
|---|---|
| **Data Source** | Taqtics API (`POST /api/v1/internal/ticket/csv/download`) |
| **Backend** | Python 3.x with pandas, requests |
| **Frontend** | HTML5, CSS3, Vanilla JavaScript |
| **Charts** | Plotly.js 2.35.0 (client-side rendering) |
| **Output** | Self-contained HTML file (2.1 MB) + Python script for regeneration |
| **Auth** | Email + Password via `TAQTICS_EMAIL` / `TAQTICS_PASSWORD` in `.env` (not committed) |

---

## Data Source & Authentication

### Pattern C API Endpoint
```
POST https://sfc.taqtics.co/api/v1/internal/ticket/csv/download
```

**Authentication quirk** (critical):
- Auth endpoint: `POST /api/v1/internal/auth/login`
- Do **NOT** add `subdomain` header to auth request — causes 401
- Data fetch headers **DO** include `subdomain: sfc`

**Credentials**: Set via local `.env` file (gitignored, not committed):
```
TAQTICS_EMAIL=<sfc account email>
TAQTICS_PASSWORD=<sfc account password>
```
- Subdomain: `sfc`

### Data Shape
- **1,739 tickets** (Jan–May 2026)
- **41 columns** including TAT metrics, dates, cost, escalation flags, activity logs
- **TAT already in minutes** — script divides by 60 for hours
- **No overdue flags in raw CSV** — computed in Python based on:
  - Closed: `Closure TAT (Hr) > SLA (Hr)`
  - Completed: `Completion TAT (Hr) > SLA (Hr)`
  - Active (Open/In Progress/On Hold): `Today > Due Date`

---

## Features Implemented

### 1. Dual Dashboard Views

#### Count View
- Default mode showing all tickets
- Active status counts (Open, In Progress, On Hold)
- Completed/Closed/Rejected counts
- Overdue subset (for quick reference)
- SLA Compliance % = (Total − Overdue) ÷ Total × 100

#### Overdue View
- Red-themed variant
- **Active overdue only** (past due date)
- **Closed/Completed overdue** (exceeded SLA)
- Aging buckets: 0–7d, 8–15d, 16–30d, 30+d
- Emphasizes tickets needing immediate attention

### 2. Key Metrics (KPI Strip)

| Card | Formula | Notes |
|---|---|---|
| **Total Tickets** | Count of all records | Shows active (unresolved) subset |
| **Open** | Status = "Open" | In Progress / On Hold breakdown |
| **Completed** | Status = "Completed" | Closed / Rejected breakdown |
| **Overdue Tickets** | Based on logic above | Aging buckets shown |
| **SLA Compliance** | (Total − Overdue) ÷ Total × 100 | Percentage of tickets within SLA |
| **Escalated** | Escalated = "Yes" | Reopened subset |
| **Status (Active)** | Open + In Progress + On Hold | Live badge breakdown |
| **Cost Recorded** | Sum of Cost column | Only shows if data exists; avg per ticket |

### 3. Visualizations

#### Row 1: Monthly Trends & Status Distribution
- **Monthly Ticket Trend** (wide): Stacked or grouped bar chart by status per month
  - Radio toggle: Stacked | Grouped
  - Legend: Open (blue), In Progress (amber), On Hold (grey), Completed (green), Closed (slate), Rejected (red)
- **Status Distribution** (narrow): Donut chart, % of each status in current view

#### Row 2: Brand & Priority Analysis
- **Tickets by Brand** (wide): Horizontal bar, count per brand
- **Priority × Status** (narrow): Stacked bars showing status breakdown per priority level

#### Row 3: Category & TAT Comparison
- **Top Categories** (half): Top 12 categories by ticket count
- **Average TAT** (half): Response / Completion / Closure TAT by Brand or Category
  - Radio toggle: By Brand | By Category
  - Radio toggle: Response | Completion | Closure TAT (one view at a time)
  - i-button tooltips explaining each TAT metric

#### Row 4: Risk & Escalation
- **Escalation by Category** (half): Count of escalated tickets per category
- **Department Attention Needed** (half): Stacked bar (High/Highest pending + Escalated) per category

#### Row 5: Recurring Issues (Month-over-Month)
- **Recurring Issues** (full width): Compares current vs previous month
  - Grey bar = previous month volume
  - Purple bar = current month volume
  - Radio toggle: By Category | By Store
  - Identifies persistent problem areas

#### Row 6: Cost Analysis
- **Cost by Category** (full width): Total cost per category
  - Radio toggle: By Category | By Sub-Category
  - Shows grand total + count of cost-recorded tickets
  - Only appears if cost data exists in filtered view

### 4. Tables

#### Store Performance Summary
- **Columns**: Store, Brand, Total, Open, In Progress, On Hold, Completed, Closed, Overdue, Escalated, Avg Response TAT
- **Sortable**: Click column header; arrow indicators
- **Paginated**: 50 rows per page
- **Searchable**: Filter by store or brand name
- **Header styling**: Dark background (#1e293b) with white text (matches reference design)

#### Ticket Details
- **19 columns** including: Ticket ID, Title, Store, Brand, Category, Sub-Category, Status, Priority, Created, Due Date, TAT metrics, Days Overdue, Escalated, Overdue flag, City, Claimed By, Activity Log button
- **Sortable**: All columns
- **Paginated**: 50 rows per page
- **Searchable**: Ticket ID, Title, Store, Category, Created By, **Claimed By**
- **Activity Log button**: Pops modal showing Events Trigger (activity log) for that ticket

#### User Performance
- **Columns**: Claimed By, Tickets, Status Breakdown (colored badges), Avg Resp TAT, Avg Comp TAT, Escalation Rate %, Reopen Rate %
- **Status Breakdown**: Color-coded count per status (Open, In Progress, On Hold, Completed, Closed, Rejected)
- **Sortable**: All except Status Breakdown
- **Paginated**: 50 rows per page
- **Search filter**: Filter users by name

### 5. Filters & Controls

#### Static Filter Bar
- **Month**: Created date only (matches Taqtics portal export)
- **Brand**: All brands + individual brand select
- **Category**: All categories + individual select
- **Status**: All statuses + individual status select
- **Priority**: All priorities + individual priority select
- **City**: All cities + individual city select
- **Date Range**: From / To date inputs (creation date range)
- **Reset Button**: Clears all filters to defaults

#### Dynamic Toggles (in charts)
- **Monthly Trend**: Stacked | Grouped
- **TAT View**: Response | Completion | Closure (radio)
- **TAT Group**: By Brand | By Category (radio)
- **Recurring Issues**: By Category | By Store (radio)
- **Cost Group**: By Category | By Sub-Category (radio)

#### Info Buttons (i)
- Appear on chart panels, table headers, and filter labels
- Hover/click to show tooltip explaining the metric or formula
- Examples: SLA definition, Response TAT formula, Days Overdue calculation, Risk Score logic

### 6. Modal & Banners

#### Activity Log Modal
- Click "Activity Log" button in Ticket Details
- Shows parsed Events Trigger as timeline entries
- Displays ticket ID, title, and activity list
- Close with × button or backdrop click

#### View Info Banner
- Click info button (i) next to Count/Overdue toggle
- Two-column banner explaining each dashboard view
- Blue background with clear bullet points
- No technical jargon

#### Overdue Mode Banner
- Red banner appears when Overdue view is active
- Reminds user they're viewing overdue-only data

---

## Data Processing Pipeline

### 1. Authentication & Fetch
```python
POST /api/v1/internal/auth/login
  → returns token, userId
  → used in all subsequent requests
POST /api/v1/internal/ticket/csv/download
  → returns CSV (text/plain)
  → parsed into pandas DataFrame
```

### 2. Column Transformations

#### Date Parsing
- Multiple format support: `"01 May 2026 02:12 PM"`, `"01 May 2026 02:12 PM"`, etc.
- Parsed into Python `datetime` objects
- `pd.NaT` for missing/invalid dates

#### TAT Conversion
```python
TAT (Hr) = TAT (Min) / 60
```
All TAT columns: SLA, Response, OnHold, Completion, Closure

#### Overdue Logic
```python
if status == "Closed":
    overdue = closure_tat_hr > sla_hr
elif status == "Completed":
    overdue = completion_tat_hr > sla_hr
elif status in ("Open", "In Progress", "On Hold"):
    overdue = today > due_date
else:  # Rejected
    overdue = False
```

#### Days Overdue
```python
if overdue:
    if status in ("Closed", "Completed"):
        days = max(0, (tat_hr - sla_hr) / 24)
    else:
        days = max(0, (now - due_date).days)
else:
    days = 0
```

#### Brand/Status/City Mapping
```python
STATUS_LABELS = {
    "open": "Open", "inProgress": "In Progress",
    "completed": "Completed", "closed": "Closed",
    "onHold": "On Hold", "rejected": "Rejected"
}
BRAND_LABELS = {
    "India_Palace": "India Palace", "sfc_Plus": "SFC Plus",
    "Golden_Dragon": "Golden Dragon", ...
}
CITY_FIX = {
    "ABU DHABI": "Abu Dhabi", "DUBAI": "Dubai"
}
```

#### Month Extraction
```python
created_month = created_date.strftime("%b%Y")  # e.g., "May2026"
completed_month = completed_date.strftime("%b%Y")
closed_month = closed_date.strftime("%b%Y")
```

### 3. Row Dictionary Construction
Each ticket becomes a JavaScript object with 40+ fields:
```javascript
{
  ticket_id: "SFC3071",
  title: "Change bank in Salary Account",
  store: "Sfcs Central Kitchen",
  brand: "SFCS",
  category: "Human Resources",
  status: "Completed",
  priority: "High",
  claimed_by: "Jaba Sarkar",
  sla_hr: 24.0,
  response_tat_hr: 15.5,
  completion_tat_hr: 15.5,
  is_overdue: false,
  days_overdue: 0,
  cost: null,
  escalated: "No",
  reopen: "No",
  created_ts: 1747632900000,  // Unix ms (for JS date filtering)
  events_trigger: "* Ticket created...\n* claimed...",
  ...
}
```

---

## Filtering Logic

### Main Filter (getFilteredRows)
Applied to all charts and tables:
```javascript
if (overdueMode && !row.is_overdue) return false;
if (state.month !== 'all' && row.month !== state.month) return false;
if (state.brand !== 'all' && row.brand !== state.brand) return false;
if (state.category !== 'all' && row.category !== state.category) return false;
if (state.status !== 'all' && row.status !== state.status) return false;
if (state.priority !== 'all' && row.priority !== state.priority) return false;
if (state.city !== 'all' && row.city !== state.city) return false;
if (state.dateFrom && row.created_ts < state.dateFrom) return false;
if (state.dateTo && row.created_ts > state.dateTo) return false;
```

### Recurring Issues Special Case
- Uses **all data ignoring month/date filters** to enable month-over-month comparison
- Filters by brand, category, status, priority, city only
- Compares previous month vs current month

---

## Styling & Theme

### Color Palette

#### Status Colors
- Open: `#3b82f6` (blue)
- In Progress: `#f59e0b` (amber)
- On Hold: `#94a3b8` (slate)
- Completed: `#10b981` (green)
- Closed: `#475569` (slate-dark)
- Rejected: `#ef4444` (red)

#### Accent Colors
- Primary: `#1a73e8` (blue)
- Overdue/Error: `#ef4444` (red)
- Success: `#10b981` (green)
- Warning: `#f97316` (orange)

#### Background & Text
- Light bg: `#f1f5f9`
- White: `#fff`
- Dark text: `#1e293b`
- Muted text: `#64748b`

#### Table Headers
- Background: `#1e293b` (dark slate)
- Text: `#fff` (white)
- Hover: `#334155` (lighter slate)

---

## File Structure

```
C:\Users\Harshit Rajput\Desktop\Custom Report of Taqtics\SFC\
├── script.py                 # Main Python script (600+ lines)
├── output.html              # Generated dashboard (2.1 MB, refreshed each run)
├── PROJECT.md              # This file
└── MASTER_CONTEXT.md       # (Reference) Taqtics platform context
```

**Generated HTML size**: ~2.1 MB (fully self-contained, no external dependencies except Plotly CDN)

---

## How to Use

### Generate/Refresh Dashboard
```bash
cd C:\Users\Harshit Rajput\Desktop\Custom Report of Taqtics\SFC
python script.py
```
Output: `output.html` (opens in any browser)

### View in Browser
```
file:///C:/Users/Harshit%20Rajput/Desktop/Custom%20Report%20of%20Taqtics/SFC/output.html
```

### Navigate Dashboard
1. **Open browser**, load HTML
2. **Select month** (defaults to latest)
3. **Apply additional filters** (brand, category, status, etc.)
4. **Toggle Count ↔ Overdue** to switch views
5. **Click info (i) buttons** to understand metrics
6. **Hover charts** for detailed numbers
7. **Search tables** by any keyword
8. **Click Activity Log** button to see ticket history
9. **Sort columns** by clicking headers
10. **Paginate** through table results

---

## Maintenance & Future Work

### Periodic Tasks
- **Weekly**: Regenerate dashboard to pull latest data
- **Monthly**: Archive previous month HTML for audit trail
- **Quarterly**: Review filter usefulness with client, adjust if needed

### Known Limitations
- No real-time updates (static HTML snapshot)
- Overdue logic excludes "Rejected" tickets (intentional)
- Month filter uses Creation Date only (matches Taqtics portal)
- Cost data sparse (~131 out of 1,739 tickets) — optional KPI card

### Potential Enhancements
- Add store-wise SLA targets (if available in Taqtics)
- Department/manager drill-down from User Performance
- Time-based SLA trends (completion time over months)
- Automated weekly email report with key metrics
- Direct Taqtics link from ticket ID (opens in platform)

---

## Reference: SFC (Southern Franchise Company LLC)

**Brands under SFC**:
- India Palace
- SFC Plus
- Golden Dragon
- SFCS (SFC Standard)
- Sthan
- Miknan
- 49ers Steakhouse
- Catering Division

**Issue Categories** (top 10):
- Human Resources
- Repairs & Maintenance
- Purchase
- IT
- SFCS (internal)
- Marketing
- Administration
- Operations
- Training
- Finance

**Locations**: UAE (Abu Dhabi, Dubai) with multiple outlets per brand

---

## Appendix: Key Formulas

### SLA Compliance
```
(Total Tickets - Overdue Count) / Total Tickets × 100
```

### Escalation Rate (per user)
```
Escalated Tickets / Total Claimed Tickets × 100
```

### Reopen Rate (per user)
```
Reopened Tickets / Total Claimed Tickets × 100
```

### Average Response TAT
```
Sum of Response TAT / Count of Tickets with Response TAT
```

### Department Risk Score (for ranking)
```
(High/Highest Priority Pending × 1) + (Escalated Pending × 1)
```

### Days Overdue (active tickets)
```
(Current Date - Due Date) / Days
```

### Days Overdue (closed/completed)
```
(TAT - SLA) / 24 Hours
```

---

## Contact & Support

**Client**: Southern Franchise Company LLC (SFC)  
**Account Email**: see local `.env` file  
**Dashboard Owner**: [Your Name]  
**Last Generated**: 02 June 2026 12:32  
**Data Current As Of**: May 2026

---

*This dashboard was built using the Taqtics Custom Reports platform (Pattern C). For API questions, consult MASTER_CONTEXT.md. For code maintenance, refer to script.py inline comments.*
