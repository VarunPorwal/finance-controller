"use client";

// Business lanes: gateway, marketplace, POS, operating, other. Each lane's
// bank and ledger movement, and what is still open inside it.

import { FcCard, FcCardHeader, FcEmpty, FcMoney } from "../_components/fc-ui";
import { plural } from "../_lib/format";
import type { CashBridge } from "../_lib/api";

export function Lanes({ lanes }: { lanes: CashBridge["lanes"] }) {
  return (
    <FcCard style={{ padding: 0 }}>
      <FcCardHeader title="Lanes" sub="Bank and ledger movement by business lane, and what is still open in it." />
      {lanes.length === 0 ? (
        <div style={{ padding: "0 16px 16px" }}>
          <FcEmpty title="No lanes for this run" sub="Lanes are assigned per counterparty in the rule scope." />
        </div>
      ) : (
        <div className="fc-scroll-x" style={{ overflowX: "auto" }}>
          <table className="fc-table" style={{ tableLayout: "auto" }}>
            <thead>
              <tr>
                <th>Lane</th>
                <th className="fc-table-num">Bank in</th>
                <th className="fc-table-num">Bank out</th>
                <th className="fc-table-num">Ledger</th>
                <th className="fc-table-num">Open</th>
                <th className="fc-table-num">Open amount</th>
              </tr>
            </thead>
            <tbody>
              {lanes.map((l) => (
                <tr key={l.lane}>
                  <td className="fc-ref">{l.lane}</td>
                  <td className="fc-table-num"><FcMoney paise={l.bank_in_paise} /></td>
                  <td className="fc-table-num"><FcMoney paise={l.bank_out_paise} /></td>
                  <td className="fc-table-num"><FcMoney paise={l.ledger_paise} /></td>
                  <td className="fc-table-num fc-num">{plural(l.exception_count, "item")}</td>
                  <td className="fc-table-num">
                    <FcMoney paise={l.unreconciled_paise} tone={l.unreconciled_paise !== 0 ? "warn" : "ok"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </FcCard>
  );
}
