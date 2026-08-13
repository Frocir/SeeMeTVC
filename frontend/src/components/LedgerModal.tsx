import type { BalanceEntry } from "../api";

const KIND_LABEL: Record<string, string> = {
  opening: "期初",
  charge: "扣费",
  refund: "退款",
  admin: "超管",
  grant: "赠送",
};

type Props = {
  title?: string;
  unit: string;
  entries: BalanceEntry[] | null;
  error?: string;
  onClose: () => void;
};

export default function LedgerModal({ title = "消费明细", unit, entries, error, onClose }: Props) {
  return (
    <div className="modal-back" onClick={onClose} role="presentation">
      <div className="modal ledger-modal" onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>
        {error && <p className="error">{error}</p>}
        {entries == null && !error && <p className="muted">加载中…</p>}
        {entries && entries.length === 0 && <p className="muted">暂无流水</p>}
        {entries && entries.length > 0 && (
          <div className="ledger-list">
            {entries.map((row) => (
              <div key={row.id} className="ledger-row">
                <div>
                  <strong>{row.title}</strong>
                  <div className="muted">
                    {KIND_LABEL[row.kind] || row.kind} · {new Date(row.created_at).toLocaleString()}
                    {row.ref_type && row.ref_id != null && (
                      <>
                        {" "}
                        · {row.ref_type} #{row.ref_id}
                      </>
                    )}
                  </div>
                </div>
                <div className="ledger-amt">
                  <strong className={row.amount < 0 ? "is-debit" : "is-credit"}>
                    {row.amount > 0 ? "+" : ""}
                    {row.amount.toFixed(2)}
                  </strong>
                  <span className="muted">
                    余 {row.balance_after.toFixed(2)} {unit}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
        <p className="muted" style={{ marginTop: 12, fontSize: "0.8rem" }}>
          每次余额变动一行（含 0 元）。旧任务不回填，期初为部署时快照。
        </p>
        <div className="modal-actions">
          <button className="primary" type="button" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
