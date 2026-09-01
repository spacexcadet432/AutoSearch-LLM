import { FileText } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PanelHeader } from "./PanelHeader";

export function AnswerPanel({ markdown }: { markdown: string }) {
  return (
    <section className="rounded-2xl border border-border bg-card/60 p-6 shadow-card-elevated backdrop-blur">
      <PanelHeader icon={FileText} label="Grounded Answer" hint="markdown" />
      <div className="prose-answer">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
      </div>
    </section>
  );
}
