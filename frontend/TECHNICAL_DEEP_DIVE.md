# Technical Deep Dive: Key Fixes and Improvements

## Problem 1: Chart and Article Appear Separate When Expanded

### The Issue
When the chart section expanded/collapsed, it appeared as a separate floating element rather than part of the card's unified content. The visual division made it seem like two stacked components rather than one cohesive unit.

### Root Causes
1. Chart was in a separate `.news-chart` container with its own margin, padding, and border
2. Both article and chart had independent transitions
3. Chart container had `border-top: 0` and `margin-top: -1px` trying to "connect" them visually
4. No shared visual container

### The Solution

#### Before:
```html
<div class="news-card">
  <div class="news-card-header"></div>
  <div class="news-card-body">
    <p class="news-summary"></p>
  </div>
  <!-- Separate chart element -->
  <div class="news-chart news-chart--linked">
    <div class="news-chart-panel"></div>
  </div>
</div>
```

#### After:
```html
<div class="card-container">
  <div class="card-header"></div>
  <!-- UNIFIED content container -->
  <div class="card-body">
    <div class="card-text">
      <p class="card-summary"></p>
    </div>
    <!-- Chart is NOW INSIDE card-body -->
    <div class="card-chart-section">
      <div class="card-chart-wrapper">
        <!-- SVG chart -->
      </div>
    </div>
  </div>
</div>
```

#### CSS Changes:
```css
/* Before: Separate animation for chart panel */
.news-chart-panel {
  max-height: 0;
  opacity: 0;
  margin-top: -1px;  /* Trying to hide separation */
  border-top: 0;     /* Trying to remove border */
}

.news-chart-panel.is-open {
  max-height: 320px;
  opacity: 1;
  margin-top: -1px;  /* Still trying to connect */
}

/* After: Unified expansion as part of card-body */
.card-chart-section {
  max-height: 0;
  overflow: hidden;
  opacity: 0;
  transition: max-height 400ms ease, opacity 300ms ease;
}

.card-chart-section.is-open {
  max-height: 500px;
  opacity: 1;
  margin-top: 24px;  /* Natural spacing from text */
}
```

**Why this works:**
- Chart section is now a child of `.card-body`
- They expand/collapse together as one unit
- No visual separation because they're in the same container
- Margin between text and chart creates intentional spacing, not a "gap"
- Single transition on parent container keeps it fluid

## Problem 2: Rigid Scrolling Container (Background Scrolling)

### The Issue
The user wanted a fixed background with only the cards scrolling, preventing the parallax-like effect of the gradient background moving.

### Root Causes in Old Design
```css
body {
  background: radial-gradient(circle at top, ...);
  overflow: auto;  /* Entire body scrolls, including background */
}

.app-main {
  padding: 32px 0 48px;
  /* No height restriction, allows body to expand */
}
```

### The Solution

#### Layout Structure:
```vue
<div class="app-viewport">
  <!-- Fixed background element -->
  <div class="app-background"></div>
  
  <!-- Header that scrolls out -->
  <header class="app-header"></header>
  
  <!-- Scrollable content only -->
  <main class="app-main"></main>
</div>
```

#### CSS Implementation:
```css
.app-viewport {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;  /* KEY: Nothing overflows */
  position: relative;
}

.app-background {
  position: fixed;  /* KEY: Stays in place! */
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: radial-gradient(...);
  z-index: -1;  /* Behind everything */
}

.app-header {
  position: relative;  /* Scrolls naturally with content */
  z-index: 100;
  /* Sticky positioning attempted, but flex makes relative work better */
}

.app-main {
  flex: 1;  /* Takes remaining space */
  overflow-y: scroll;  /* Only this scrolls */
  overflow-x: hidden;
  scroll-behavior: smooth;
}

html, body, #__nuxt {
  height: 100%;
  overflow: hidden;  /* Prevent body overflow */
}
```

**Why this works:**
- `app-viewport` is 100vh with `overflow: hidden` → rigid container
- `app-background` is `position: fixed` → never scrolls
- `app-main` has `overflow-y: scroll` → only content area scrolls
- Header is within main, so it scrolls out naturally
- No overflow at body level = no background movement

## Problem 3: Header Scroll Detection

### The Issue
Need to know when user has scrolled to change header styling (reduce opacity, increase background).

### The Solution

```vue
<script setup>
const isHeaderScrolled = ref(false)

function onScroll(e) {
  isHeaderScrolled.value = e.target.scrollTop > 0
}
</script>

<template>
  <header class="app-header" :class="{ 'is-scrolled': isHeaderScrolled }">
    <!-- content -->
  </header>
  <main class="app-main" @scroll="onScroll">
    <!-- content -->
  </main>
</template>

<style scoped>
.app-header {
  background: rgba(255, 255, 255, 0.75);
  transition: background 280ms ease;
}

.app-header.is-scrolled {
  background: rgba(255, 255, 255, 0.95);
}
</style>
```

**Key points:**
- Scroll event fires on `.app-main` (the scrollable element)
- `e.target.scrollTop` tells us how far user has scrolled
- Class toggles dynamically for smooth transition

## Problem 4: Chart Unification in Current vs Historical Cards

### The Challenge
Current card should always show chart (expanded).
Historical cards should have toggle-able charts.
Both should feel unified.

### The Solution

#### In HourlyCard.vue:
```javascript
const props = defineProps({
  isCurrent: {
    type: Boolean,
    default: false,
  },
})

// Current card: chart always open
const chartOpen = ref(props.isCurrent)

function toggleChart() {
  if (hasPriceSeries.value) {
    chartOpen.value = !chartOpen.value
  }
}
```

```css
/* Current card: chart always visible, no animation */
.card-container.is-current .card-chart-section {
  max-height: none;
  opacity: 1;
  overflow: visible;
  margin-top: 0;
  transition: none;
}

/* Historical card: chart toggles with animation */
.card-chart-section {
  max-height: 0;
  overflow: hidden;
  opacity: 0;
  transition: max-height 400ms ease, opacity 300ms ease;
}

.card-chart-section.is-open {
  max-height: 500px;
  opacity: 1;
  margin-top: 24px;
}
```

**Why this works:**
- Same component handles both scenarios
- `isCurrent` prop determines initial state
- CSS uses `:not()` selectors to override for current card
- No "jump" between states

## Problem 5: Infinite Scroll with Sentinel Element

### The Issue
Need to detect when user scrolls near bottom to load more cards.
Previous implementation had scroll event listeners on cards, not optimal.

### The Solution

#### Composable:
```javascript
export const useInfiniteScroll = (fetchFunction, options = {}) => {
  const sentinel = ref(null)
  
  onMounted(() => {
    if (sentinel.value) {
      // Intersection Observer: fires when sentinel enters viewport
      const observer = new IntersectionObserver(
        (entries) => {
          const [entry] = entries
          if (entry.isIntersecting && hasMore.value && !isLoading.value) {
            loadMore()  // Load next page
          }
        },
        { rootMargin: `${threshold}px` }  // Load 500px before end
      )
      
      observer.observe(sentinel.value)
    }
  })
}
```

#### In Template:
```vue
<div ref="sentinel" class="scroll-sentinel"></div>
<!-- When this enters viewport, load more -->
```

**Why this is better:**
- No constant scroll event listeners (performance)
- Intersection Observer API is efficient
- `rootMargin` means load before user actually reaches bottom
- Automatic cleanup on unmount

## Animation: Card Entrance

### Staggered Animation

```css
@keyframes card-enter {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.card-container {
  animation: card-enter 400ms ease forwards;
  animation-delay: var(--animation-delay, 0ms);
}
```

```vue
<HourlyCard
  v-for="(card, index) in cards"
  :key="card.id"
  :style="{ '--animation-delay': `${index * 50}ms` }"
/>
```

**How it works:**
- Each card animates individually
- Delay is set via CSS custom property
- Creates cascading effect as cards appear
- Property can be adjusted globally in one place

## End of List Design

### Visual Design

```css
.end-of-list {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 60px 20px;
}

.end-of-list-visual {
  width: 40px;
  height: 2px;
  background: linear-gradient(to right, transparent, var(--line), transparent);
  position: relative;
}

.end-of-list-visual::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 6px;
  height: 6px;
  background: var(--ink-soft);
  border-radius: 50%;
}

.end-of-list-text {
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-soft);
}
```

**Design elements:**
- Horizontal line fades at edges (gradient)
- Centered dot in middle (using ::before)
- Uppercase label below
- Generous padding creates breathing room
- Colors use design tokens (--ink-soft, --line)

## SVG Chart Rendering

### Why SVG?
- Responsive (scales with viewBox)
- Precise control over every element
- No external charting library needed
- Full control over styling

### Structure:
```html
<svg viewBox="0 0 720 280">
  <!-- Grid lines -->
  <g class="chart-grid">
    <line x1="..." x2="..." y1="..." y2="..."/>
  </g>
  
  <!-- Axis labels -->
  <g class="chart-axis">
    <text x="..." y="...">Label</text>
  </g>
  
  <!-- Price guides (High/Low/Last) -->
  <g class="chart-guide">
    <line/>  <!-- Dashed line -->
    <text/>  <!-- Price label -->
  </g>
  
  <!-- Candlesticks -->
  <line/>  <!-- Wick (high-low line) -->
  <rect/>  <!-- Body (open-close rectangle) -->
</svg>
```

### Data Transformation:

```javascript
function buildChartData(rows, expectedCount) {
  // 1. Get bounds (drawing area)
  const bounds = chartConfig.bounds
  
  // 2. Find price range
  const highs = rows.map(r => Number(r.high))
  const lows = rows.map(r => Number(r.low))
  const max = Math.max(...highs)
  const min = Math.min(...lows)
  const range = max - min
  
  // 3. Create scale function (price → pixel position)
  const scaleY = (value) =>
    bounds.top + ((max - value) / range) * (bounds.bottom - bounds.top)
  
  // 4. Draw candlesticks
  const candles = rows.map((row, index) => {
    const centerX = bounds.left + index * step + step / 2
    const openY = scaleY(Number(row.open))
    const closeY = scaleY(Number(row.close))
    const highY = scaleY(Number(row.high))
    const lowY = scaleY(Number(row.low))
    
    return {
      x: centerX,
      highY, lowY,  // For wick
      bodyX, bodyY, bodyWidth, bodyHeight,  // For rectangle
      color: closeY >= openY ? '#2f7f5e' : '#b34b4b',  // Green up, red down
    }
  })
  
  // 5. Generate axis labels and price guides
  // ... (see code for details)
  
  return { candles, yTicks, xT icks, priceLines, ... }
}
```

## Performance Optimizations

### 1. Intersection Observer Instead of Scroll Events
- No throttling/debouncing needed
- Auto-cleanup on unmount
- Native browser API

### 2. Computed Properties for Card Filtering
```javascript
const historicalHourlyCards = computed(() => {
  return infiniteScroll.items.value.filter(card => 
    !card.is_daily_summary && card.id !== currentCard.value?.id
  )
})
```
- Reactively updates when items change
- No manual filtering in template loops

### 3. Card Keys Prevent Re-renders
```vue
<HourlyCard
  v-for="card in cards"
  :key="`hourly-${card.id}`"  <!-- Unique key -->
  :card="card"
/>
```
- Vue can track and reuse components
- Prevents full re-render of card list

### 4. SVG Charts vs Canvas/Painted Charts
- Smoother on low-end devices
- Vectorized (zoom-safe)
- No repainting on every scroll

## Responsive Design

### Breakpoints
```css
@media (max-width: 640px) {
  /* Adjust padding, chart height, font sizes */
}
```

### Flexible Container
```css
.app-shell {
  width: min(820px, 100%);  /* Max 820px, or 100% if smaller */
  padding: 0 22px;           /* Side padding on narrow screens */
}
```

## Summary of Key Improvements

| Problem | Solution | Benefit |
|---------|----------|---------|
| Chart looked separate | Chart now inside card-body | Unified visual appearance |
| Background scrolled | position: fixed on background | Fixed background effect |
| No scroll indicator | .is-scrolled class on header | Visual feedback |
| Charts toggle awkward | Smooth max-height transition | Fluid animation |
| No infinite scroll | Intersection Observer | Efficient loading |
| Unclear end of list | Custom design with line & dot | Beautiful UX |
| Current card identical to others | is-current prop with CSS overrides | Visual hierarchy |
| Choppy scrolling | scroll-behavior: smooth | Better feel |

All of these improvements work together to create a sophisticated, professional frontend application that properly handles the hourly/daily card structure and provides excellent user experience.
