"use client";

import { useEffect, useState } from "react";
import {
  Coins,
  History,
  KeyRound,
  LoaderCircle,
  Receipt,
  Sparkles,
  Ticket,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  api,
  type CreditPricing,
  type CreditTransaction,
  type UserWallet,
} from "@/lib/api";

type CreditCenterDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  wallet: UserWallet | null;
  onWalletUpdated: (wallet: UserWallet) => void;
};

type ActiveTab = "pricing" | "redeem" | "history";

export function CreditCenterDialog({
  open,
  onOpenChange,
  wallet,
  onWalletUpdated,
}: CreditCenterDialogProps) {
  const [activeTab, setActiveTab] = useState<ActiveTab>("pricing");
  const [pricing, setPricing] = useState<CreditPricing | null>(null);
  const [transactions, setTransactions] = useState<CreditTransaction[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [code, setCode] = useState("");
  const [redeeming, setRedeeming] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (!open) return;
    setFeedback(null);
    void api.getPricing().then(setPricing).catch(console.error);
    void api.getWallet().then(onWalletUpdated).catch(console.error);
  }, [open, onWalletUpdated]);

  useEffect(() => {
    if (!open || activeTab !== "history") return;
    setLoadingHistory(true);
    void api
      .getCreditTransactions(50, 0)
      .then(setTransactions)
      .catch((err) =>
        setFeedback({
          type: "error",
          text: err instanceof Error ? err.message : "获取明细失败",
        })
      )
      .finally(() => setLoadingHistory(false));
  }, [open, activeTab]);

  const handleRedeem = async () => {
    const trimmed = code.trim();
    if (!trimmed) {
      setFeedback({ type: "error", text: "请输入有效的兑换码" });
      return;
    }
    setRedeeming(true);
    setFeedback(null);
    try {
      const res = await api.redeemCreditCode(trimmed);
      setFeedback({
        type: "success",
        text: `兑换成功！已增加 ${res.credits_added} 积分，当前余额 ${res.new_balance} 积分`,
      });
      setCode("");
      const updatedWallet = await api.getWallet();
      onWalletUpdated(updatedWallet);
    } catch (err) {
      setFeedback({
        type: "error",
        text: err instanceof Error ? err.message : "兑换失败，请检查卡密是否正确或已被使用",
      });
    } finally {
      setRedeeming(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/65 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="积分中心"
    >
      <Card className="w-full max-w-xl border-white/10 bg-zinc-950/95 text-zinc-100 shadow-2xl shadow-black/50">
        <CardHeader className="border-b border-white/10 pb-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle className="flex items-center gap-2 text-xl">
                <Sparkles className="size-5 text-amber-400" />
                积分中心
              </CardTitle>
              <CardDescription className="mt-2 text-zinc-400">
                查看可用积分、扣费标准与卡密充值兑换
              </CardDescription>
            </div>
            <Button
              variant="ghost"
              size="icon"
              aria-label="关闭积分中心"
              onClick={() => onOpenChange(false)}
            >
              <X />
            </Button>
          </div>

          {/* 积分总览卡片 */}
          <div className="mt-4 grid grid-cols-3 gap-2 rounded-xl border border-white/10 bg-white/[0.03] p-3 text-center">
            <div>
              <p className="text-xs text-zinc-400">可用积分</p>
              <p className="mt-1 text-2xl font-bold tracking-tight text-amber-300">
                {wallet?.balance ?? 0}
              </p>
            </div>
            <div className="border-x border-white/10">
              <p className="text-xs text-zinc-400">任务冻结中</p>
              <p className="mt-1 text-2xl font-bold tracking-tight text-zinc-300">
                {wallet?.frozen ?? 0}
              </p>
            </div>
            <div>
              <p className="text-xs text-zinc-400">累计消耗</p>
              <p className="mt-1 text-2xl font-bold tracking-tight text-zinc-400">
                {wallet?.total_spent ?? 0}
              </p>
            </div>
          </div>

          {/* Tab 导航 */}
          <div className="mt-4 flex gap-2 rounded-xl bg-white/[0.04] p-1">
            <Button
              type="button"
              variant={activeTab === "pricing" ? "secondary" : "ghost"}
              className="flex-1 text-xs"
              onClick={() => setActiveTab("pricing")}
            >
              <Receipt className="size-3.5 mr-1" />
              计费规则
            </Button>
            <Button
              type="button"
              variant={activeTab === "redeem" ? "secondary" : "ghost"}
              className="flex-1 text-xs"
              onClick={() => setActiveTab("redeem")}
            >
              <Ticket className="size-3.5 mr-1" />
              卡密兑换
            </Button>
            <Button
              type="button"
              variant={activeTab === "history" ? "secondary" : "ghost"}
              className="flex-1 text-xs"
              onClick={() => setActiveTab("history")}
            >
              <History className="size-3.5 mr-1" />
              消费明细
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-4 pt-4 max-h-[55vh] overflow-y-auto">
          {feedback ? (
            <div
              className={`rounded-xl border p-3 text-sm ${
                feedback.type === "success"
                  ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-200"
                  : "border-red-300/20 bg-red-300/10 text-red-200"
              }`}
            >
              {feedback.text}
            </div>
          ) : null}

          {/* 计费规则 Tab */}
          {activeTab === "pricing" ? (
            <div className="space-y-2">
              <p className="text-xs text-zinc-400">
                平台执行长任务前先冻结积分；任务生成失败或取消时，积分自动原路退还。
              </p>
              <div className="divide-y divide-white/5 rounded-xl border border-white/10 bg-white/[0.02]">
                {pricing?.items.map((item, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between p-3 text-sm hover:bg-white/[0.02]"
                  >
                    <div>
                      <p className="font-medium text-zinc-200">{item.name}</p>
                      <p className="text-xs text-zinc-400">{item.description}</p>
                    </div>
                    <Badge variant="outline" className="border-amber-400/30 text-amber-300">
                      {item.cost === 0 ? "免费" : `${item.cost} 积分 / ${item.unit}`}
                    </Badge>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* 卡密兑换 Tab */}
          {activeTab === "redeem" ? (
            <div className="space-y-4 py-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-zinc-200">输入兑换卡密</label>
                <div className="flex gap-2">
                  <Input
                    placeholder="输入卡密代码，例如 LENS-ABCD-1234"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    disabled={redeeming}
                    className="flex-1 uppercase font-mono tracking-wider"
                  />
                  <Button
                    type="button"
                    disabled={redeeming || !code.trim()}
                    onClick={() => void handleRedeem()}
                    className="bg-amber-500 hover:bg-amber-400 text-black font-semibold"
                  >
                    {redeeming ? <LoaderCircle className="animate-spin size-4" /> : "立即兑换"}
                  </Button>
                </div>
              </div>
              <p className="text-xs text-zinc-400 leading-relaxed">
                内测体验码或充值卡密可在输入后一次性核销入账。如需测试码，可联系系统管理员生成。
              </p>
            </div>
          ) : null}

          {/* 消费明细 Tab */}
          {activeTab === "history" ? (
            <div className="space-y-2">
              {loadingHistory ? (
                <div className="flex items-center justify-center py-8 text-zinc-400 text-sm">
                  <LoaderCircle className="animate-spin mr-2 size-4" />
                  加载明细中...
                </div>
              ) : transactions.length === 0 ? (
                <div className="py-8 text-center text-zinc-500 text-sm">
                  暂无积分变动记录
                </div>
              ) : (
                <div className="divide-y divide-white/5 rounded-xl border border-white/10 bg-white/[0.02]">
                  {transactions.map((tx) => (
                    <div
                      key={tx.id}
                      className="flex items-center justify-between p-3 text-xs hover:bg-white/[0.02]"
                    >
                      <div className="space-y-0.5">
                        <p className="font-medium text-zinc-200">{tx.description}</p>
                        <p className="text-[11px] text-zinc-500">
                          {new Date(tx.created_at).toLocaleString("zh-CN", {
                            month: "2-digit",
                            day: "2-digit",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </p>
                      </div>
                      <div className="text-right">
                        <span
                          className={`font-semibold font-mono text-sm ${
                            tx.amount > 0 ? "text-emerald-400" : "text-zinc-400"
                          }`}
                        >
                          {tx.amount > 0 ? `+${tx.amount}` : tx.amount}
                        </span>
                        <p className="text-[10px] text-zinc-500">
                          结余 {tx.balance_after}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
