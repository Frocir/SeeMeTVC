import { useEffect, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { api, type AdminUser, type Channel } from "../api";
import { useAuth } from "../auth";

const emptyChannel = {
  name: "",
  provider: "fal",
  base_url: "https://queue.fal.run",
  api_key: "",
  model_id: "seedance-lite",
  upstream_model: "fal-ai/bytedance/seedance/v1/lite/text-to-video",
  cost_per_second: 1,
  priority: 10,
  enabled: true,
  remark: "",
};

export default function AdminPage() {
  const { me } = useAuth();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [form, setForm] = useState(emptyChannel);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  async function reload() {
    const [chs, us] = await Promise.all([
      api<Channel[]>("/api/admin/channels"),
      api<AdminUser[]>("/api/admin/users"),
    ]);
    setChannels(chs);
    setUsers(us);
  }

  useEffect(() => {
    if (me?.role === "super_admin") void reload().catch((e) => setError(String(e.message || e)));
  }, [me]);

  if (me?.role !== "super_admin") return <Navigate to="/" replace />;

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError("");
    setMsg("");
    try {
      await api("/api/admin/channels", { method: "POST", body: JSON.stringify(form) });
      setForm(emptyChannel);
      setMsg("渠道已添加");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "失败");
    }
  }

  async function toggle(ch: Channel) {
    await api(`/api/admin/channels/${ch.id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled: !ch.enabled }),
    });
    await reload();
  }

  async function setBalance(userId: number, balance: number) {
    await api(`/api/admin/users/${userId}/balance`, {
      method: "PATCH",
      body: JSON.stringify({ balance }),
    });
    await reload();
  }

  return (
    <section className="admin">
      <h1>超级管理</h1>
      <p className="muted">添加上游 token 来源（API Key 渠道），并设置用户余额。</p>

      <div className="admin-grid">
        <form className="panel" onSubmit={onCreate}>
          <h2>新增渠道</h2>
          {(
            [
              ["name", "名称"],
              ["provider", "provider (fal/mock)"],
              ["base_url", "Base URL"],
              ["api_key", "API Key"],
              ["model_id", "对外模型 ID"],
              ["upstream_model", "上游模型路径"],
              ["remark", "备注"],
            ] as const
          ).map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                value={String(form[key])}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                required={key !== "remark" && key !== "base_url"}
              />
            </label>
          ))}
          <label>
            每秒消耗余额
            <input
              type="number"
              step="0.01"
              value={form.cost_per_second}
              onChange={(e) => setForm({ ...form, cost_per_second: Number(e.target.value) })}
            />
          </label>
          <label>
            优先级
            <input
              type="number"
              value={form.priority}
              onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })}
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            />
            启用
          </label>
          {error && <p className="error">{error}</p>}
          {msg && <p className="ok">{msg}</p>}
          <button type="submit">保存渠道</button>
        </form>

        <div className="panel">
          <h2>渠道列表</h2>
          {channels.map((ch) => (
            <div className="channel-item" key={ch.id}>
              <div>
                <strong>{ch.name}</strong>
                <div className="muted">
                  {ch.model_id} · {ch.provider} · Key {ch.api_key_masked}
                </div>
                <div className="muted">
                  {ch.cost_per_second}/秒 · 优先级 {ch.priority} · {ch.enabled ? "已启用" : "已停用"}
                </div>
              </div>
              <button type="button" className="ghost" onClick={() => void toggle(ch)}>
                {ch.enabled ? "停用" : "启用"}
              </button>
            </div>
          ))}
        </div>

        <div className="panel wide">
          <h2>用户余额</h2>
          <div className="table">
            <div className="row head">
              <span>邮箱</span>
              <span>角色</span>
              <span>余额</span>
              <span>操作</span>
            </div>
            {users.map((u) => (
              <div className="row" key={u.id}>
                <span>{u.email}</span>
                <span>{u.role}</span>
                <span>{u.balance.toFixed(2)}</span>
                <span>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => {
                      const next = window.prompt("设置余额", String(u.balance));
                      if (next == null) return;
                      void setBalance(u.id, Number(next));
                    }}
                  >
                    改余额
                  </button>
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
