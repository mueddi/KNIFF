import { useMemo } from "react";
import "katex/dist/katex.min.css";
import { buildHtml } from "./mathHtml.js";

export default function MathText({ text }) {
  const html = useMemo(() => buildHtml(text), [text]);
  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}
