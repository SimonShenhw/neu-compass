// Paste into the browser console on the scripts/answer_render_check.py page once every case has
// rendered. Prints counts only (see that script's docstring). 中文：页面全部渲染后粘贴到浏览器控制台，
// 只输出计数（说明见 answer_render_check.py 的文档串）。
(() => {
  const CATALOG = /^https:\/\/catalog\.northeastern\.edu\/course-descriptions\/[a-z]{2,8}\/(#[A-Za-z0-9_-]+)?$/;
  const CATALOG_AT = /^https:\/\/catalog\.northeastern\.edu\/course-descriptions\/[a-z]{2,8}\//;
  const URL_START = /https?:\/\/|www\./gi;
  const WORD_JOINER = String.fromCharCode(0x2060);
  const r = {cases: 0, byKind: {}, noMarkdown: 0, links: {catalog: 0, mail: 0, headingAnchor: 0, other: 0},
             embedded: 0, katex: 0, styled: 0, urlInText: 0, urlInCode: 0, plainMismatch: {}};
  // Streamlit's own markup that is not from the answer: the spans of each heading and its anchor,
  // code highlighting, and the copy button next to each code block. Directive, icon and coloured-text
  // elements count inside headings too; only code blocks are skipped for them. 中文：不是来自回答的
  // Streamlit 自带元素：标题的 span 和锚点、代码高亮、代码块旁的复制按钮。指令、图标、彩色文字在标题里
  // 也计数，只跳过代码块里的。
  const inCodeBlock = (element) => element.closest('pre')
    || element.querySelector('button[aria-label="Copy to clipboard"]');
  const streamlitOwn = (element) => inCodeBlock(element) || element.closest('h1,h2,h3,h4,h5,h6');
  for (const box of document.querySelectorAll('[class*="st-key-case-"]')) {
    const key = [...box.classList].find((name) => name.startsWith('st-key-case-')).slice(12);
    const kind = key.split('-')[0];
    r.cases++;
    r.byKind[kind] = (r.byKind[kind] || 0) + 1;
    const md = box.querySelector('[data-testid="stMarkdownContainer"]');
    if (!md) { r.noMarkdown++; continue; }
    for (const a of md.querySelectorAll('a')) {
      const href = a.getAttribute('href') || '';
      if (CATALOG.test(href)) r.links.catalog++;
      else if (href.startsWith('mailto:')) r.links.mail++;
      else if (href.startsWith('#') && a.closest('h1,h2,h3,h4,h5,h6') && a.textContent === '') r.links.headingAnchor++;
      else r.links.other++;
    }
    if (md.querySelector('img, image, svg image, iframe, video, audio, object, embed, picture, source')) r.embedded++;
    if (md.querySelector('.katex, .katex-display, math')) r.katex++;
    const plain = [...md.querySelectorAll('span, small')].filter((element) => !streamlitOwn(element));
    // Directive output in Streamlit 1.57: coloured text and background, badges, shimmer, icons, and
    // the inline-styled span of :small[]. 中文：Streamlit 1.57 的指令产物：彩色文字和背景、徽章、
    // 闪烁效果、图标，以及 :small[] 的内联样式 span。
    const marked = [...md.querySelectorAll('[data-testid^="stIcon"], [class*="Badge"], [class*="ColoredText"], '
      + '[class*="ColoredBackground"], [class*="Shimmer"], span[style]')]
      .filter((element) => !inCodeBlock(element));
    if (plain.length || marked.length) r.styled++;  // Directives, icons, coloured text or tooltips from the answer.
    for (const code of md.querySelectorAll('code')) {
      for (const match of code.textContent.matchAll(URL_START)) {
        if (!CATALOG_AT.test(code.textContent.slice(match.index))) { r.urlInCode++; break; }
      }
    }
    const clone = md.cloneNode(true);
    clone.querySelectorAll('a, code, pre').forEach((element) => element.remove());
    const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (/https?:\/\/|www\./i.test(node.nodeValue)) { r.urlInText++; break; }
    }
    if (kind === 'plain') {
      const expected = box.querySelector('[data-testid="stText"]').textContent;
      const shown = md.textContent.split(WORD_JOINER).join('');
      if (shown !== expected) {
        let i = 0;
        while (i < shown.length && shown[i] === expected[i]) i++;
        const pair = JSON.stringify(expected.slice(i, i + 2)) + ' -> ' + JSON.stringify(shown.slice(i, i + 2));
        r.plainMismatch[pair] = (r.plainMismatch[pair] || 0) + 1;
      }
    }
  }
  console.log(JSON.stringify(r, null, 2));
  return r;
})();
