<template>
  <article class="prose-page">
    <h1>About NousNews</h1>
    <p>
      NousNews gives you a quick read on what happened in the financial markets and how prices reacted. Every 4 hours
      we publish a short brief on the news that matters to markets, with the price charts of major assets for
      the same period beside it. Once a day is over, its briefs are combined into one article for that day.
    </p>

    <h2>How the briefs are made</h2>
    <p>
      An automated pipeline reads public news feeds from established financial and economic publishers and keeps
      only stories likely to move markets: central banks, inflation and jobs data, earnings, commodities, credit
      and geopolitics. An AI language model then writes the brief from those stories. Every brief links to the
      original sources so you can check them.
    </p>
    <p>
      For the most important briefs, we publish a follow-up a little later that compares what the brief described
      with how prices actually moved afterwards.
    </p>

    <h2>What NousNews is not</h2>
    <p>
      Briefs are written by software, not by a newsroom, and can contain mistakes. NousNews does not give
      investment advice. Read the <NuxtLink to="/disclaimer">disclaimer</NuxtLink> before acting on anything
      you read here.
    </p>

    <h2>Get in touch</h2>
    <p>Found an error or have a suggestion? <NuxtLink to="/contact">Contact us</NuxtLink>.</p>
  </article>
</template>

<script setup>
useSeoMeta({
  title: 'About · NousNews',
  description: 'What NousNews is, how the market briefs are produced, and where the information comes from.',
})
</script>
