"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type TextareaHTMLAttributes } from "react";
import { createPortal } from "react-dom";
import { FileImage, Film, Hash, Image, Layers3, Sparkles, Type, Video } from "lucide-react";

import { Textarea } from "@/components/ui/textarea";

export type MentionType = "asset" | "node" | "shot" | "generation";

export type MentionRef = {
  type: MentionType;
  id: string;
  label: string;
};

export type MentionOption = MentionRef & {
  subtitle?: string;
  kind?: string;
};

type MentionPickerProps = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange"> & {
  value: string;
  options: MentionOption[];
  mentions?: MentionRef[];
  onChange: (value: string) => void;
  onMentionsChange?: (mentions: MentionRef[]) => void;
  onMentionSelect?: (option: MentionOption) => void;
  wrapperClassName?: string;
};

function optionIcon(option: MentionOption) {
  if (option.type === "asset") {
    return option.kind === "video" ? <Film /> : option.kind === "audio" ? <Video /> : <FileImage />;
  }
  if (option.type === "node") return <Layers3 />;
  if (option.type === "generation") return option.kind === "video" ? <Film /> : <Sparkles />;
  if (option.type === "shot") return <Hash />;
  return <Image />;
}

function typeLabel(type: MentionType): string {
  return type === "asset" ? "资产" : type === "node" ? "节点" : type === "generation" ? "生成结果" : "镜头";
}

function mentionToken(label: string): string {
  return `@${label.replace(/\s+/g, "-")}`;
}

export function MentionPicker({
  value,
  options,
  mentions = [],
  onChange,
  onMentionsChange,
  onMentionSelect,
  wrapperClassName = "",
  ...textareaProps
}: MentionPickerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const selectionRef = useRef({ start: value.length, end: value.length });
  const [active, setActive] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [menuRect, setMenuRect] = useState<{ left: number; bottom: number; width: number } | null>(null);

  const mentionQuery = useMemo(() => {
    const beforeCursor = value.slice(0, selectionRef.current.start);
    const match = beforeCursor.match(/(?:^|\s)@([^\s@]*)$/);
    if (!match) return null;
    return {
      start: beforeCursor.length - match[0].length + (match[0].startsWith(" ") ? 1 : 0),
      end: beforeCursor.length,
      query: match[1] ?? "",
    };
  }, [value]);

  const filteredOptions = useMemo(() => {
    if (!mentionQuery) return [];
    const query = mentionQuery.query.trim().toLocaleLowerCase();
    return options.filter((option) => (
      !query
      || option.label.toLocaleLowerCase().includes(query)
      || option.subtitle?.toLocaleLowerCase().includes(query)
      || option.kind?.toLocaleLowerCase().includes(query)
    )).slice(0, 12);
  }, [mentionQuery, options]);

  useEffect(() => {
    setActive(Boolean(mentionQuery));
    setActiveIndex((current) => Math.min(current, Math.max(filteredOptions.length - 1, 0)));
  }, [filteredOptions.length, mentionQuery]);

  useEffect(() => {
    if (!active) {
      setMenuRect(null);
      return;
    }
    const updatePosition = () => {
      const rect = textareaRef.current?.getBoundingClientRect();
      if (!rect) return;
      setMenuRect({
        left: rect.left + 8,
        bottom: Math.max(window.innerHeight - rect.top + 9, 8),
        width: Math.max(rect.width - 16, 260),
      });
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [active]);

  const selectOption = (option: MentionOption) => {
    if (!mentionQuery) return;
    const before = value.slice(0, mentionQuery.start);
    const after = value.slice(mentionQuery.end);
    const token = `${mentionToken(option.label)} `;
    const nextValue = `${before}${token}${after}`;
    onChange(nextValue);
    onMentionsChange?.([
      ...mentions.filter((mention) => mention.id !== option.id || mention.type !== option.type),
      { type: option.type, id: option.id, label: option.label },
    ]);
    onMentionSelect?.(option);
    setActive(false);
    const nextCursor = before.length + token.length;
    selectionRef.current = { start: nextCursor, end: nextCursor };
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(nextCursor, nextCursor);
    });
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (active && filteredOptions.length) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveIndex((current) => (current + 1) % filteredOptions.length);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveIndex((current) => (current - 1 + filteredOptions.length) % filteredOptions.length);
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        selectOption(filteredOptions[activeIndex]);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setActive(false);
        return;
      }
    }
    textareaProps.onKeyDown?.(event);
  };

  return (
    <div className={`mention-picker ${wrapperClassName}`}>
      <Textarea
        {...textareaProps}
        ref={textareaRef}
        value={value}
        onChange={(event) => {
          const nextValue = event.currentTarget.value;
          selectionRef.current = {
            start: event.currentTarget.selectionStart,
            end: event.currentTarget.selectionEnd,
          };
          onChange(nextValue);
          onMentionsChange?.(mentions.filter((mention) => nextValue.includes(mentionToken(mention.label))));
        }}
        onSelect={(event) => {
          selectionRef.current = {
            start: event.currentTarget.selectionStart,
            end: event.currentTarget.selectionEnd,
          };
          textareaProps.onSelect?.(event);
        }}
        onKeyDown={handleKeyDown}
        onFocus={(event) => {
          selectionRef.current = {
            start: event.currentTarget.selectionStart,
            end: event.currentTarget.selectionEnd,
          };
          textareaProps.onFocus?.(event);
        }}
      />
      {active && menuRect && typeof document !== "undefined" ? createPortal(
        <div
          className="mention-picker__menu mention-picker__menu--portal"
          role="listbox"
          aria-label="可引用内容"
          style={menuRect}
        >
          <div className="mention-picker__hint"><span>@</span>引用画布节点、项目资产或生成结果</div>
          {filteredOptions.map((option, index) => (
            <button
              key={`${option.type}:${option.id}`}
              type="button"
              role="option"
              aria-selected={index === activeIndex}
              className={index === activeIndex ? "is-active" : undefined}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => selectOption(option)}
            >
              <span className="mention-picker__icon">{optionIcon(option)}</span>
              <span className="mention-picker__copy"><strong>{option.label}</strong><small>{option.subtitle ?? typeLabel(option.type)}</small></span>
              <em>{typeLabel(option.type)}</em>
            </button>
          ))}
          {filteredOptions.length === 0 ? <div className="mention-picker__empty">当前镜头暂无匹配的可引用内容</div> : null}
          <div className="mention-picker__footer">↑↓ 选择 · Enter 引用 · Esc 关闭</div>
        </div>,
        document.body,
      ) : null}
    </div>
  );
}
