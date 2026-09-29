"use client";

import Link from "next/link";
import { useCallback, useRef, useState } from "react";
import { HomeComposer } from "@/components/home-composer";
import { inspirationCases, type InspirationCase } from "@/data/inspiration-cases";

export default function Home() {
  const [prefillPrompt, setPrefillPrompt] = useState("");
  const [activeCaseId, setActiveCaseId] = useState<number | null>(null);
  const composerRef = useRef<HTMLDivElement>(null);

  const fillAgentFromCase = useCallback((caseItem: InspirationCase) => {
    setPrefillPrompt(caseItem.prompt);
    setActiveCaseId(caseItem.id);
    // 让 Agent Chat 输入框滚到视口，用户看到 prompt 已填入
    requestAnimationFrame(() => {
      composerRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      composerRef.current?.querySelector("textarea")?.focus();
    });
   }, []);

  return <main className="showcase-home">
    <nav className="showcase-nav"><div className="showcase-logo"><span>✦</span> 灵感工场</div><div className="showcase-nav-links"><a href="#cases">案例</a><Link href="/dashboard">进入工作台 ↗</Link></div></nav>
     <section className="showcase-hero"><h1>今天，想创作什么？</h1><p className="showcase-intro">告诉 Agent 你的想法，从第一句话开始创作；或点击下方案例，一键把提示词填入 Agent Chat。</p></section>
     <div ref={composerRef}>
       <HomeComposer prefillPrompt={prefillPrompt} activeCase={activeCaseId ? inspirationCases.find((c) => c.id === activeCaseId) : null} onClearCase={() => { setPrefillPrompt(""); setActiveCaseId(null); }} />
     </div>
     <section id="cases" className="showcase-cases">
       <div className="showcase-section-head">
         <div><p className="showcase-kicker">SELECTED WORKS</p><h2>灵感案例</h2></div>
         <span>点击卡片 · 提示词自动填入上方 Agent Chat · {inspirationCases.length} 个精选案例</span>
       </div>
       <div className="showcase-grid">
         {inspirationCases.map((caseItem) => (
             <article
              key={caseItem.id}
              className={`showcase-card ${activeCaseId === caseItem.id ? "is-filled" : ""}`}
              onClick={() => fillAgentFromCase(caseItem)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  fillAgentFromCase(caseItem);
                 }
               }}
              role="button"
              tabIndex={0}
              aria-label={`将「${caseItem.keywords}」的提示词填入 Agent Chat`}
             >
               <img src={caseItem.picture} alt={caseItem.keywords} loading="lazy" />
               <div className="showcase-card-meta">
                 <div className="showcase-card-meta-tags">
                   <span>{caseItem.keywords}</span>
                   {caseItem.size ? <span className="showcase-card-meta-sub">{caseItem.size}</span> : null}
                   {caseItem.qualityLevel ? <span className="showcase-card-meta-sub">{caseItem.qualityLevel}</span> : null}
                 </div>
                 <strong>{activeCaseId === caseItem.id ? "已填入 ↑" : "填入 Agent →"}</strong>
               </div>
               {activeCaseId === caseItem.id ? <div className="showcase-card-filled" aria-hidden="true">已填入</div> : null}
             </article>
           ))}
       </div>
     </section>
   </main>;
}
