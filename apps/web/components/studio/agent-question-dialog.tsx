"use client";

import { Dialog } from "@base-ui/react/dialog";
import { Check, ChevronLeft, ChevronRight, LoaderCircle, Pencil, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { AgentInterrupt, AgentQuestion, AgentQuestionAnswer } from "@/lib/api";

type Props = {
  interrupt: AgentInterrupt;
  open: boolean;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (response: Record<string, unknown>) => Promise<void>;
};

function blankAnswer(question: AgentQuestion): AgentQuestionAnswer {
  return { question_id: question.id, option_ids: [], text: "", skipped: false };
}

export function AgentQuestionDialog({ interrupt, open, loading, error, onClose, onSubmit }: Props) {
  const legacyOptions = interrupt.payload.options ?? [];
  const payloadQuestions = interrupt.payload.questions ?? [];
  // Older runs can contain a selection interrupt with no options. Treat it
  // as an open question rather than rendering an empty, non-actionable card.
  const form = interrupt.kind === "question_form" || (!payloadQuestions.length && !legacyOptions.length);
  const questions: AgentQuestion[] = payloadQuestions.length ? payloadQuestions : [{
    id: interrupt.id, title: interrupt.title, description: interrupt.description,
    kind: form ? "text" : interrupt.kind === "multi_select" ? "multi_select" : "single_select",
    options: legacyOptions,
  }];
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, AgentQuestionAnswer>>({});
  const [customIds, setCustomIds] = useState<string[]>([]);
  const submittingRef = useRef(false);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const question = questions[index];
  const answer = answers[question.id] ?? blankAnswer(question);
  const custom = question.kind === "text" || customIds.includes(question.id);
  const multi = question.kind === "multi_select";
  const ready = (value?: AgentQuestionAnswer) => Boolean(value && (
    value.skipped || value.text.trim() || value.option_ids.length
  ));

  useEffect(() => {
    if (open) titleRef.current?.focus();
  }, [index, open]);

  const choose = (id: string) => {
    setCustomIds((current) => current.filter((value) => value !== question.id));
    const ids = multi
      ? answer.option_ids.includes(id) ? answer.option_ids.filter((value) => value !== id) : [...answer.option_ids, id]
      : [id];
    setAnswers((current) => ({ ...current, [question.id]: { ...blankAnswer(question), option_ids: ids } }));
  };

  const advance = async (nextAnswers = answers) => {
    if (loading || submittingRef.current) return;
    if (index < questions.length - 1) {
      setIndex(index + 1);
      return;
    }
    const missing = questions.findIndex((item) => !ready(nextAnswers[item.id]));
    if (missing >= 0) {
      setIndex(missing);
      return;
    }
    submittingRef.current = true;
    try {
      const currentAnswer = nextAnswers[question.id];
      await onSubmit(form ? {
        answers: questions.map((item) => nextAnswers[item.id]),
      } : multi ? { option_ids: currentAnswer.option_ids } : { option_id: currentAnswer.option_ids[0] });
    } catch {
      // The parent exposes the API error; keep all answers for retry.
    } finally {
      submittingRef.current = false;
    }
  };

  const skip = () => {
    const updated = { ...answers, [question.id]: { ...blankAnswer(question), skipped: true } };
    setAnswers(updated);
    setCustomIds((current) => current.filter((value) => value !== question.id));
    void advance(updated);
  };

  return (
    <Dialog.Root open={open} onOpenChange={(next) => { if (!next && !loading) onClose(); }} disablePointerDismissal>
      <Dialog.Portal>
        <Dialog.Backdrop className="agent-questions__backdrop" />
        <Dialog.Popup className="agent-questions" aria-busy={loading}>
          <header className="agent-questions__navigation">
            <Dialog.Close render={<Button variant="ghost" size="icon" />} disabled={loading} aria-label="暂时收起问题">
              <X />
            </Dialog.Close>
            <div>
              <Button variant="ghost" size="icon" aria-label="上一题" disabled={loading || index === 0} onClick={() => setIndex(index - 1)}><ChevronLeft /></Button>
              <span aria-live="polite">{index + 1} / {questions.length}</span>
              <Button variant="ghost" size="icon" aria-label="下一题" disabled={loading || index === questions.length - 1} onClick={() => setIndex(index + 1)}><ChevronRight /></Button>
            </div>
            {form ? <Button variant="ghost" disabled={loading} onClick={skip}>跳过此题</Button> : <span />}
          </header>

          <div className="agent-questions__body">
            <Dialog.Title ref={titleRef} tabIndex={-1} className="agent-questions__title">{question.title}</Dialog.Title>
            <Dialog.Description className="agent-questions__description">
              {question.description || (question.kind === "text" ? "写下你的想法，也可以先跳过。" : multi ? "可选择多个，也可以填写自己的答案。" : "选择一个方向，或填写自己的答案。")}
            </Dialog.Description>
            <fieldset className="agent-questions__options" disabled={loading}>
              <legend className="sr-only">{question.title}</legend>
              {question.options.map((option, optionIndex) => {
                const selected = !custom && answer.option_ids.includes(option.id);
                return (
                  <label key={option.id} className={`agent-questions__option ${selected ? "is-selected" : ""}`}>
                    <input type={multi ? "checkbox" : "radio"} name={`question-${question.id}`} checked={selected} onChange={() => choose(option.id)} />
                    <span className={`agent-questions__number ${multi ? "is-checkbox" : ""}`} aria-hidden="true">{selected ? <Check /> : optionIndex + 1}</span>
                    <span className="agent-questions__option-text"><strong>{option.label}</strong>{option.caption ? <span>{option.caption}</span> : null}</span>
                  </label>
                );
              })}
              {form && question.kind !== "text" ? (
                <Button className={`agent-questions__custom ${custom ? "is-selected" : ""}`} variant="ghost" onClick={() => {
                  setCustomIds((current) => [...current.filter((id) => id !== question.id), question.id]);
                  setAnswers((current) => ({ ...current, [question.id]: { ...blankAnswer(question), text: answer.text } }));
                }}>
                  <span className="agent-questions__number"><Pencil /></span>填写自己的答案
                </Button>
              ) : null}
              {form && custom ? <Textarea
                className="agent-questions__text" aria-label={`${question.title}：自定义回答`} placeholder="输入你的想法…" maxLength={2000}
                value={answer.text} autoFocus={question.kind !== "text"}
                onChange={(event) => setAnswers((current) => ({ ...current, [question.id]: { ...blankAnswer(question), text: event.target.value } }))}
              /> : null}
            </fieldset>
            {answer.skipped ? <p className="agent-questions__skipped">此题已跳过，可返回修改。跳过不会批准任何操作。</p> : null}
            {error ? <p className="agent-questions__error" role="alert">{error}</p> : null}
          </div>

          <footer className="agent-questions__footer">
            <span>{questions.filter((item) => ready(answers[item.id])).length} / {questions.length} 已填写</span>
            <Button disabled={loading || !ready(answer)} onClick={() => void advance()}>
              {loading ? <LoaderCircle className="animate-spin" /> : null}
              {loading ? "正在继续…" : index < questions.length - 1 ? "下一题" : "提交并继续"}
              {!loading ? <ChevronRight /> : null}
            </Button>
          </footer>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
