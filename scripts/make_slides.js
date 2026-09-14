/* Build docs/media/slides.pptx — the open/close slides for the demo video.
 * Brand: ink #26251E, paper #FFFFFF (clean), sage #3E5C50, amber #B07D2E.
 * Run: node scripts/make_slides.js
 */
const pptxgen = require("pptxgenjs");

const INK = "26251E";
const PAPER = "FFFFFF";
const SAGE = "3E5C50";
const SAGE_SOFT = "E8EFE9";
const AMBER = "B07D2E";
const MUTED = "726D5F";
const FAINT = "A49E8D";
const SERIF = "Cambria";
const SANS = "Calibri";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5

// ---------------------------------------------------------------- slide 1
{
  const s = pres.addSlide();
  s.background = { color: INK };
  s.addText([
    { text: "Epilogue", options: { fontFace: SERIF, fontSize: 88, color: "F2EFE6" } },
    { text: ".", options: { fontFace: SERIF, fontSize: 88, color: AMBER } },
  ], { x: 0.9, y: 2.35, w: 11.5, h: 1.6, isTextBox: true, margin: 0 });
  s.addText("The agent that settles what's left behind.", {
    x: 0.95, y: 3.95, w: 11.5, h: 0.6, fontFace: SERIF, fontSize: 26, italic: true,
    color: "CFC9B8", isTextBox: true, margin: 0,
  });
  s.addText("Built on the Strands Agents SDK  ·  Amazon Bedrock  ·  AWS “Agents for Humans” 2026  ·  Shivam Gupta", {
    x: 0.95, y: 6.6, w: 11.5, h: 0.4, fontFace: SANS, fontSize: 14, color: "8D8770",
    isTextBox: true, margin: 0,
  });
  s.addNotes("This is Epilogue — a project by Shivam Gupta, built on the Strands Agents SDK. It's an agent for the hardest week of ordinary life.");
}

// ---------------------------------------------------------------- slide 2
{
  const s = pres.addSlide();
  s.background = { color: PAPER };
  s.addText("When someone dies, their family inherits a second job.", {
    x: 0.9, y: 0.7, w: 11.5, h: 0.7, fontFace: SERIF, fontSize: 30, color: INK,
    isTextBox: true, margin: 0,
  });
  s.addText([
    { text: "420 hours", options: { fontFace: SERIF, fontSize: 110, color: SAGE } },
    { text: ".", options: { fontFace: SERIF, fontSize: 110, color: AMBER } },
  ], { x: 0.9, y: 1.7, w: 8.4, h: 2.0, isTextBox: true, margin: 0 });
  s.addText("of paperwork, phone trees, forms, and follow-ups — over 12–18 months, at the worst moment of a family's life. The British have a word for it: “sadmin.”", {
    x: 0.95, y: 3.75, w: 7.6, h: 1.1, fontFace: SANS, fontSize: 17, color: MUTED,
    isTextBox: true, margin: 0,
  });

  const cards = [
    ["3.4M", "deaths per year in the US alone — each one starts this clock"],
    ["10+", "institutions to notify, each demanding its own certified documents"],
    ["800K", "deceased Americans have their identity misused every year — “ghosting”"],
    ["1 month", "of benefits clawed back — the payment for the month of death must be returned"],
  ];
  cards.forEach(([num, label], i) => {
    const x = 0.9 + (i % 2) * 6.0;
    const y = 5.1 + Math.floor(i / 2) * 1.15;
    s.addShape(pres.ShapeType.roundRect, {
      x, y, w: 5.7, h: 1.0, fill: { color: SAGE_SOFT }, rectRadius: 0.08, line: { type: "none" },
    });
    s.addText(num, { x: x + 0.25, y: y + 0.12, w: 1.7, h: 0.75, fontFace: SERIF, fontSize: 28, color: SAGE, isTextBox: true, margin: 0, valign: "middle" });
    s.addText(label, { x: x + 2.0, y: y + 0.1, w: 3.6, h: 0.8, fontFace: SANS, fontSize: 11.5, color: INK, isTextBox: true, margin: 0, valign: "middle" });
  });
  s.addNotes("Researchers estimate it at more than four hundred hours over a year or more…");
}

// ---------------------------------------------------------------- slide 3
{
  const s = pres.addSlide();
  s.background = { color: PAPER };
  s.addText("Built for Sarah.", {
    x: 0.9, y: 0.7, w: 11.5, h: 0.9, fontFace: SERIF, fontSize: 40, color: INK, isTextBox: true, margin: 0,
  });
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.9, y: 1.9, w: 6.6, h: 4.4, fill: { color: "FBF9F3" }, line: { color: "E5DFD2", width: 1 }, rectRadius: 0.1,
  });
  s.addText([
    { text: "Grieving her father — and back at work already.\n", options: { breakLine: true } },
    { text: "Two states away from the house, the mail, the paperwork.\n", options: { breakLine: true } },
    { text: "Executor of the estate: every institution is her job now.\n", options: { breakLine: true } },
    { text: "Terrified of missing something — or losing his photos.", options: {} },
  ], {
    x: 1.25, y: 2.25, w: 5.9, h: 3.7, fontFace: SANS, fontSize: 17, color: INK,
    isTextBox: true, margin: 0, lineSpacingMultiple: 1.55,
  });
  s.addShape(pres.ShapeType.roundRect, {
    x: 8.0, y: 1.9, w: 4.4, h: 4.4, fill: { color: INK }, rectRadius: 0.1, line: { type: "none" },
  });
  s.addText("“The agent runs autonomously and only surfaces when there's a real decision to make.”", {
    x: 8.35, y: 2.3, w: 3.7, h: 2.3, fontFace: SERIF, fontSize: 19, italic: true, color: "F2EFE6",
    isTextBox: true, margin: 0, lineSpacingMultiple: 1.3,
  });
  s.addText("— the hackathon brief.\nWe took it to the place\nit matters most.", {
    x: 8.35, y: 4.8, w: 3.7, h: 1.3, fontFace: SANS, fontSize: 14, color: "B9B29C",
    isTextBox: true, margin: 0, lineSpacingMultiple: 1.25,
  });
  s.addNotes("It lands on people like Sarah — grieving, back at work, two states away…");
}

// ---------------------------------------------------------------- slide 4
{
  const s = pres.addSlide();
  s.background = { color: PAPER };
  // architecture.png is 2480x1760 (ratio 1.409); fit height 6.9 → width 9.72
  s.addImage({ path: "docs/media/architecture.png", x: 1.8, y: 0.45, w: 9.72, h: 6.9 });
  s.addNotes("Under the hood: six Strands agents. A Steward orchestrator with specialists mounted as tools…");
}

// ---------------------------------------------------------------- slide 5
{
  const s = pres.addSlide();
  s.background = { color: PAPER };
  s.addText("Is this a company? It already is — twice.", {
    x: 0.9, y: 0.7, w: 11.5, h: 0.9, fontFace: SERIF, fontSize: 36, color: INK, isTextBox: true, margin: 0,
  });
  const cols = [
    ["$90M", "raised by Empathy for human-powered after-loss support — sold through insurers and employers. The demand is proven; the labor model is the constraint.", "VALIDATED MARKET"],
    ["≈ $8", "in model cost per full case on Bedrock — against 400+ hours of family time. Agents collapse the marginal cost of care.", "AGENTIC UNIT ECONOMICS"],
    ["B2B2C", "life insurers, employers, banks, and funeral homes already pay for bereavement support. Epilogue is the benefit they hand to a family.", "DISTRIBUTION"],
  ];
  cols.forEach(([num, body, tag], i) => {
    const x = 0.9 + i * 4.0;
    s.addShape(pres.ShapeType.roundRect, {
      x, y: 2.0, w: 3.7, h: 4.5, fill: { color: i === 1 ? SAGE : "FBF9F3" },
      line: i === 1 ? { type: "none" } : { color: "E5DFD2", width: 1 }, rectRadius: 0.1,
    });
    const fg = i === 1 ? "FFFFFF" : INK;
    const dim = i === 1 ? "CFE0D5" : MUTED;
    s.addText(tag, { x: x + 0.3, y: 2.35, w: 3.1, h: 0.35, fontFace: SANS, fontSize: 11, color: i === 1 ? "CFE0D5" : FAINT, charSpacing: 2, isTextBox: true, margin: 0 });
    s.addText(num, { x: x + 0.3, y: 2.75, w: 3.1, h: 1.1, fontFace: SERIF, fontSize: 44, color: i === 1 ? "FFFFFF" : SAGE, isTextBox: true, margin: 0 });
    s.addText(body, { x: x + 0.3, y: 3.95, w: 3.1, h: 2.4, fontFace: SANS, fontSize: 13.5, color: i === 1 ? dim : MUTED, isTextBox: true, margin: 0, lineSpacingMultiple: 1.2 });
  });
  s.addNotes("Is this real? 3.4 million American families face this every year…");
}

// ---------------------------------------------------------------- slide 6
{
  const s = pres.addSlide();
  s.background = { color: INK };
  s.addText("The hardest week of ordinary life\ndeserves an agent for humans.", {
    x: 0.9, y: 2.3, w: 11.5, h: 1.9, fontFace: SERIF, fontSize: 40, color: "F2EFE6",
    isTextBox: true, margin: 0, lineSpacingMultiple: 1.2,
  });
  s.addText([
    { text: "Epilogue", options: { fontFace: SERIF, fontSize: 30, color: "F2EFE6" } },
    { text: ".", options: { fontFace: SERIF, fontSize: 30, color: AMBER } },
    { text: "   github.com/shi1720/afh-aws  ·  MIT licensed  ·  Strands Agents SDK  ·  Amazon Bedrock", options: { fontFace: SANS, fontSize: 14, color: "8D8770" } },
  ], { x: 0.95, y: 5.6, w: 11.8, h: 0.7, isTextBox: true, margin: 0, valign: "middle" });
  s.addNotes("The hardest week of ordinary life deserves an agent for humans. This is Epilogue. Thank you.");
}

pres.writeFile({ fileName: "docs/media/slides.pptx" }).then(() => console.log("slides.pptx written"));
