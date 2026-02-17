# NousNews Frontend - New Architecture Documentation

## Overview

The frontend has been completely redesigned to implement a sophisticated hourly and daily card system with real-time updates, infinite scroll, and unified chart/article display.

## Key Features

### 1. **Rigid Scrolling Container**
- The entire viewport is now fixed at 100vh with no overflow
- Fixed background gradient (no longer scrolls)
- Header stays in place while content scrolls beneath
- Main content area has overflow-y: scroll with smooth scrolling

### 2. **Current Hour Card**
- Always displayed at the top of the content area
- Larger visual prominence (larger title, full chart visibility)
- Auto-updates every 20 seconds as agent runs
- Shows the current hour's article and price candles
- Unified chart section that expands/collapses smoothly

### 3. **Hourly Historical Cards**
- Display previous hourly briefs below the current card
- Read-only (no updates after creation)
- Collapsible chart sections using smooth animations
- Chart and article are unified (chart isn't separate from text)
- Trigger expand/collapse by clicking the card header

### 4. **Daily Summary Cards**
- Appear after hourly cards in the scroll
- 24-hour combined analysis and market summary
- Special visual treatment with date divider line
- Include badge showing "24-Hour Summary"
- Link to related economics article

### 5. **Infinite Scroll**
- Loads more cards as user scrolls to bottom
- Intersection Observer pattern for efficiency
- Configurable page size and threshold
- Beautiful end-of-list indicator (centered line with dot)

### 6. **Card Filtering**
The system separates cards based on the `is_daily_summary` flag:
```javascript
// Hourly cards: is_daily_summary === false or undefined
// Daily cards: is_daily_summary === true
```

You must update your backend API to return this flag when appropriate.

## Component Structure

### Layout: `layouts/default.vue`
- Main viewport container
- Fixed background
- Sticky header
- Scrollable main content area
- Manages scroll state for header styling

### Components

#### `components/HourlyCard.vue`
```vue
<HourlyCard 
  :card="cardObject" 
  :is-current="true|false"
/>
```
- Props: `card` (object), `isCurrent` (boolean)
- Features:
  - Toggleable chart section
  - Multiple price series tabs
  - SVG candlestick charts
  - Responsive design

#### `components/DailyCard.vue`
```vue
<DailyCard 
  :card="cardObject"
  :related-article-id="articleId"
/>
```
- Props: `card` (object), `relatedArticleId` (string|number)
- Features:
  - Special date divider
  - 24-Hour Summary badge
  - Related article link
  - Same chart functionality as hourly cards

### Composable: `composables/useInfiniteScroll.js`
```javascript
const infiniteScroll = useInfiniteScroll(
  fetchFunction,
  {
    threshold: 500,      // Load more 500px before end
    pageSize: 10,        // Items per page
    autoLoad: true       // Auto-load on scroll
  }
)

// Usage:
// infiniteScroll.items      - current items array
// infiniteScroll.isLoading  - loading state
// infiniteScroll.hasMore    - has more items to load
// infiniteScroll.loadMore() - manual load trigger
// infiniteScroll.reset()    - reset pagination
```

## Card Data Structure

Each card object must include:

```javascript
{
  id: "card-id",
  title: "Market Brief",
  summary: "Article content...",
  hour_start: "2026-02-08T13:00:00Z",  // or created_at
  is_daily_summary: false,              // true for daily cards
  price_series: [
    {
      label: "BTC/USD",
      symbol: "BTCUSD",
      candles: [
        {
          timestamp: "2026-02-08 13:00",
          open: 43500,
          high: 43800,
          low: 43400,
          close: 43700
        },
        // ... more candles
      ],
      expected_count: 60  // expected number of candles for hourly
    },
    // ... more price series
  ],
  related_article_id: "article-123"  // for daily cards
}
```

## Styling Changes

### CSS Variables (unchanged)
```css
--bg, --bg-soft, --ink, --ink-soft, --line, --accent, 
--accent-soft, --glass, --shadow, --shadow-soft, --radius
```

### Key Style Classes
- `.card-container` - Hourly card wrapper
- `.card-header` - Card header (always visible)
- `.card-body` - Card content area
- `.card-chart-section` - Expandable chart area (unified with card)
- `.daily-card` - Daily summary card wrapper
- `.end-of-list` - End of scroll indicator
- `.loading-indicator` - Loading spinner

### Chart Styling
- Grid lines fade
- Axis labels are muted
- Price guides show High/Low/Last prices
- Candlestick colors: green (up) = #2f7f5e, red (down) = #b34b4b

## API Integration

Your `useNewsApi()` composable must support:

```javascript
// Get current hour card (updates frequently)
api.getLastHour() 
// Returns single card object

// Get historical briefs (paginated)
api.getBriefs({ page: 0, limit: 10 })
// Returns { results: [...cards], count: number }

// Get single article
api.getArticle(id)
// Returns card/article object
```

## Responsive Design

The layout is fully responsive:
- Mobile: Cards adjust padding, charts height reduced
- Tablet/Desktop: Full layout with proper spacing
- Header remains sticky throughout
- Content area scrolls independently

## Animation Details

### Card Entrance
```css
animation: card-enter 400ms ease forwards;
```
- Slight upward slide with fade-in
- Staggered by `--animation-delay` CSS variable

### Chart Expand/Collapse
```css
transition: max-height 400ms ease, opacity 300ms ease;
```
- Smooth height expansion
- Opacity fade for visual continuity
- Chart and article stay together

### Loading Spinner
```css
animation: spin 800ms linear infinite;
```
- Rotating border animation
- Shows during infinite scroll load

## End of List Design

When no more cards available:
- Horizontal line with centered dot
- Text: "You've reached the beginning of our records"
- Centered, with generous padding
- Beautiful, minimalist aesthetic

## Implementation Notes

1. **Chart Unity Fix**: The key fix for the chart appearing separate was:
   - Remove margin between chart and article sections when expanded
   - Use single unified container (`card-chart-section`)
   - Apply transition to container, not separate elements
   - Chart is part of card-body, not floating element

2. **Fixed Background**: 
   - Applied `background` to fixed overlay element (`app-background`)
   - `position: fixed` prevents scrolling
   - `z-index: -1` keeps it behind everything

3. **Scrolling Header**:
   - Header uses `position: relative` (not sticky)
   - Scrolls with content naturally
   - `.is-scrolled` class toggles on scroll event
   - Background opacity increases when scrolled

4. **Infinite Scroll**:
   - Uses Intersection Observer API
   - Sentinel element at bottom triggers load
   - Efficient, doesn't scroll main element repeatedly

## Testing Checklist

- [ ] Current card displays and updates every 20 seconds
- [ ] Charts expand/collapse smoothly
- [ ] No visual separation between chart and article when expanded
- [ ] Scroll down triggers infinite load
- [ ] End of list shows beautiful indicator
- [ ] Mobile responsiveness works
- [ ] Header stays scrollable
- [ ] Background stays fixed
- [ ] Price series tabs switch correctly
- [ ] Daily cards show 24-hour badge
- [ ] Related article link works on daily cards

## Future Enhancements

- Add filtering by asset/symbol
- Add date range picker
- Add card pinning/saving
- Add price alerts
- Add social sharing
- Add dark mode toggle
- Add export to CSV functionality
