// Assembles the GitHub Pages site in _site/: the product page (site/), the deck viewer and slides (deck/, once it
// exists), and the images both use (docs/images/). No build step beyond copying files.
// Run from the repo root: node scripts/build-site.mjs, then serve _site/ with any static server.
import { cp, rm, access } from 'node:fs/promises';

const out = '_site';
const exists = async p => access(p).then(() => true, () => false);
await rm(out, { recursive: true, force: true });
await cp('site', out, { recursive: true });
if (await exists('deck')) await cp('deck', `${out}/deck`, { recursive: true });
if (await exists('docs/images')) await cp('docs/images', `${out}/images`, { recursive: true, filter: src => !src.endsWith('.md') });
console.log(`Built ${out}/`);
