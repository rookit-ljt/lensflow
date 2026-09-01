"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronDown,
  ExternalLink,
  Heart,
  Plus,
  Search,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { AgentSkill } from "@/lib/api";

export type ChatSkill = AgentSkill & {
  instruction: string;
  origin: "builtin" | "custom";
};

type SkillLibraryProps = {
  open: boolean;
  skills: AgentSkill[];
  selectedSkillId?: string | null;
  onClose: () => void;
  onSelect: (skill: ChatSkill | null) => void;
};

type SkillTab = "通用" | "收藏" | "我的";

const customStorageKey = "libtv.chat-skills.v1";
const favoriteStorageKey = "libtv.chat-skill-favorites.v1";

function readStorage<T>(key: string, fallback: T): T {
  try {
    const value = window.localStorage.getItem(key);
    return value ? JSON.parse(value) as T : fallback;
  } catch {
    return fallback;
  }
}

function toChatSkill(skill: AgentSkill): ChatSkill {
  return { ...skill, instruction: skill.instruction ?? "", origin: "builtin" };
}

export function SkillLibrary({ open, skills, selectedSkillId, onClose, onSelect }: SkillLibraryProps) {
  const [tab, setTab] = useState<SkillTab>("通用");
  const [query, setQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [customSkills, setCustomSkills] = useState<ChatSkill[]>([]);
  const [favorites, setFavorites] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instruction, setInstruction] = useState("");

  useEffect(() => {
    if (!open) return;
    setCustomSkills(readStorage<ChatSkill[]>(customStorageKey, []));
    setFavorites(readStorage<string[]>(favoriteStorageKey, []));
  }, [open]);

  const allSkills = useMemo(() => [...skills.map(toChatSkill), ...customSkills], [customSkills, skills]);
  const visibleSkills = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return allSkills.filter((skill) => {
      if (tab === "通用" && skill.origin !== "builtin") return false;
      if (tab === "收藏" && !favorites.includes(skill.id)) return false;
      if (tab === "我的" && skill.origin !== "custom") return false;
      if (normalized && ![skill.name, skill.slug, skill.description, ...skill.tags].join(" ").toLocaleLowerCase().includes(normalized)) return false;
      return true;
    });
  }, [allSkills, favorites, query, tab]);

  const toggleFavorite = (skill: ChatSkill) => {
    const next = favorites.includes(skill.id)
      ? favorites.filter((id) => id !== skill.id)
      : [...favorites, skill.id];
    setFavorites(next);
    window.localStorage.setItem(favoriteStorageKey, JSON.stringify(next));
  };

  const createSkill = () => {
    const trimmedName = name.trim();
    const trimmedInstruction = instruction.trim();
    if (!trimmedName || !trimmedInstruction) return;
    const id = `custom-${crypto.randomUUID()}`;
    const next: ChatSkill = {
      id,
      name: trimmedName,
      slug: `/${trimmedName.toLocaleLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "-").replace(/^-|-$/g, "")}`,
      description: description.trim() || "我的自定义创作 Skill",
      category: "我的",
      tags: ["自定义"],
      source: "我的 Skill",
      source_url: "",
      stars: null,
      license: "个人规则",
      featured: false,
      instruction: trimmedInstruction,
      origin: "custom",
    };
    const nextSkills = [next, ...customSkills];
    setCustomSkills(nextSkills);
    window.localStorage.setItem(customStorageKey, JSON.stringify(nextSkills));
    setTab("我的");
    setShowCreate(false);
    setName("");
    setDescription("");
    setInstruction("");
    onSelect(next);
  };

  if (!open) return null;

  return (
    <section className="skill-library" aria-label="Skill 库">
      <header className="skill-library__header">
        <div><span className="skill-library__eyebrow">AGENT PLAYBOOK</span><h2>Skill</h2></div>
        <div className="skill-library__header-actions">
          <Button type="button" variant="outline" onClick={() => setShowCreate((current) => !current)}><Plus />创建 <ChevronDown className={showCreate ? "is-open" : undefined} /></Button>
          <Button type="button" variant="outline" onClick={() => setTab("通用")} aria-label="显示全部 Skill">全部</Button>
          <Button type="button" variant="ghost" size="icon-sm" onClick={onClose} aria-label="关闭"><X /></Button>
        </div>
      </header>

      <div className="skill-library__toolbar">
        <nav className="skill-library__tabs" aria-label="Skill 分类">
          {(["通用", "收藏", "我的"] as SkillTab[]).map((item) => <button key={item} type="button" className={tab === item ? "is-active" : undefined} onClick={() => setTab(item)}>{item}</button>)}
        </nav>
        <label className="skill-library__search"><Search /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 Skill" /></label>
      </div>

      {showCreate ? (
        <div className="skill-library__create">
          <div className="skill-library__create-heading"><Sparkles /><strong>创建我的 Skill</strong><span>写清楚 Agent 应该如何工作</span></div>
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="名称，例如：古典武侠广告导演" />
          <Input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="一句话描述这个 Skill" />
          <Textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="输入创作规则、检查清单和输出格式…" rows={3} />
          <div className="skill-library__create-actions"><Button type="button" variant="ghost" onClick={() => setShowCreate(false)}>取消</Button><Button type="button" onClick={createSkill} disabled={!name.trim() || !instruction.trim()}><Check />保存 Skill</Button></div>
        </div>
      ) : null}

      <div className="skill-library__list">
        {visibleSkills.length ? visibleSkills.map((skill) => {
          const selected = selectedSkillId === skill.id;
          const favorite = favorites.includes(skill.id);
          return (
            <article className={`skill-library__item ${selected ? "is-selected" : ""}`} key={skill.id}>
              <button type="button" className="skill-library__item-main" onClick={() => onSelect(selected ? null : skill)}>
                <span className="skill-library__icon"><Wrench /></span>
                <span className="skill-library__copy"><strong>{skill.name}</strong><code>{skill.slug}</code><small>{skill.description}</small><span className="skill-library__tags">{skill.tags.map((tag) => <em key={tag}>{tag}</em>)}</span></span>
              </button>
              <div className="skill-library__item-actions">
                {selected ? <Badge className="skill-library__selected-badge"><Check />已启用</Badge> : null}
                {skill.stars ? <Badge variant="outline">★ {skill.stars}</Badge> : null}
                <button type="button" className={favorite ? "is-favorite" : undefined} onClick={() => toggleFavorite(skill)} aria-label={favorite ? "取消收藏" : "收藏"}><Heart /></button>
                {skill.source_url ? <a href={skill.source_url} target="_blank" rel="noreferrer" aria-label="查看来源"><ExternalLink /></a> : null}
              </div>
            </article>
          );
        }) : <div className="skill-library__empty"><Wrench /><strong>还没有匹配的 Skill</strong><span>尝试搜索“分镜”“首尾帧”或创建自己的 Skill。</span></div>}
      </div>
    </section>
  );
}
