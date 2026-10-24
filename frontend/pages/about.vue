<template>
  <article class="prose-page">
    <h1>About NousNews</h1>
    <p>
      Markets move on news, and most coverage only tells you half of it. NousNews puts the story and the price
      reaction on the same page. Every 4 hours we publish a sharp brief on the headlines that mattered, with charts
      of stocks, bonds, gold, oil, currencies and crypto over the same window. When the day closes, its briefs are
      folded into one article you can read in a few minutes.
    </p>

    <h2>How the briefs are made</h2>
    <p>
      An automated pipeline reads public feeds from central banks, financial publishers and global news monitors,
      and throws out the noise. What stays is what moves markets: central banks, inflation and jobs data,
      earnings, commodities, credit and geopolitics. An AI language model then writes the brief from those stories. Every brief links to the
      original sources so you can check them.
    </p>
    <p>
      For the biggest stories we come back later with a follow-up that checks the call: what the brief said, and
      how prices actually moved afterwards.
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
