"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { CheckSquare, Bug as BugIcon, BookOpen, ListTodo } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMyWork } from "@/hooks/useMyWork";
import { MyAssignedTask } from "@/lib/api";

const TYPE_META: Record<string, { icon: typeof CheckSquare; color: string }> = {
  task: { icon: CheckSquare, color: "text-blue-400" },
  bug: { icon: BugIcon, color: "text-red-400" },
  story: { icon: BookOpen, color: "text-purple-400" },
};

export default function MyWorkPage() {
  const t = useTranslations("myWork");
  const [includeDone, setIncludeDone] = useState(false);
  const { data: items = [], isLoading } = useMyWork({ include_done: includeDone });

  const counts = useMemo(() => {
    return items.reduce<Record<string, number>>((acc, item) => {
      acc[item.item_type] = (acc[item.item_type] || 0) + 1;
      return acc;
    }, {});
  }, [items]);

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-3xl font-bold text-foreground flex items-center gap-3">
              <ListTodo className="h-8 w-8 text-primary-500" />
              {t("title")}
            </h1>
            <p className="text-muted-foreground mt-2">{t("description")}</p>
          </div>
          <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer">
            <input
              type="checkbox"
              checked={includeDone}
              onChange={(e) => setIncludeDone(e.target.checked)}
              className="rounded border-border text-primary-500 focus:ring-primary-500"
            />
            {t("showCompleted")}
          </label>
        </div>

        <div className="flex gap-3 mb-6 text-sm text-muted-foreground">
          <span>{t("totalCount", { count: items.length })}</span>
          {Object.entries(counts).map(([type, count]) => (
            <span key={type}>
              · {TYPE_META[type] ? t(`typeCount.${type}`, { count }) : `${count} ${type}`}
            </span>
          ))}
        </div>

        {isLoading ? (
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-16 bg-muted rounded-lg animate-pulse" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-16 text-muted-foreground">
            <ListTodo className="h-12 w-12 mx-auto mb-3 opacity-50" />
            <p>{t("empty")}</p>
          </div>
        ) : (
          <div className="space-y-2">
            {items.map((item) => (
              <MyWorkRow key={`${item.item_type}-${item.id}`} item={item} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MyWorkRow({ item }: { item: MyAssignedTask }) {
  const t = useTranslations("myWork");
  const meta = TYPE_META[item.item_type] ?? TYPE_META.task;
  const typeKey = TYPE_META[item.item_type] ? item.item_type : "task";
  const Icon = meta.icon;
  const row = (
    <div className="flex items-center justify-between gap-3 p-3 bg-muted/50 border border-border rounded-lg hover:bg-muted transition">
      <div className="flex items-center gap-3 min-w-0">
        <Icon className={`h-4 w-4 shrink-0 ${meta.color}`} />
        <div className="min-w-0">
          <div className="text-sm text-foreground truncate">{item.title}</div>
          {item.sprint_name && (
            <div className="text-xs text-muted-foreground truncate">{item.sprint_name}</div>
          )}
        </div>
      </div>
      <div className="flex items-center gap-3 shrink-0 text-xs text-muted-foreground">
        <span className="uppercase tracking-wider">{t(`types.${typeKey}`)}</span>
        {item.story_points != null && (
          <span className="px-1.5 py-0.5 bg-accent rounded">
            {t("points", { count: item.story_points })}
          </span>
        )}
        <span className="capitalize">{item.priority}</span>
        <span className="capitalize">{item.status.replace(/_/g, " ")}</span>
      </div>
    </div>
  );

  return item.sprint_id && item.project_id ? (
    <Link href={`/sprints/${item.project_id}/${item.sprint_id}`} className="block">
      {row}
    </Link>
  ) : (
    <div>{row}</div>
  );
}
