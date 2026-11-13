"""`fml assets`: regenerate every chart, the headline, and the site data from saved results.
No cluster needed."""

from __future__ import annotations

import json
import shutil

import numpy as np

from fml import REPO_ROOT, results
from fml.replay import agreement
from fml.site import build as site_build
from fml.viz import charts, scenario_check, theme

SITE = REPO_ROOT / "site"


def headline(summary: dict) -> dict:
    t = summary["table"]

    def mean(key, field):
        return t[key][field]["mean"]

    rec_d = t["new_fraud_pattern/drift"]["per_seed"]
    rec_s = t["new_fraud_pattern/scheduled"]["per_seed"]

    def days(rows) -> str | None:
        got = [r["time_to_recover"] for r in rows if r["time_to_recover"] is not None]
        if not got:
            return None
        never = len(rows) - len(got)
        out = f"{sum(got) / len(got):.0f} simulated days"
        return out + (f" ({never} of {len(rows)} seeds never recovered)" if never else "")

    d_share = 100 * mean("new_fraud_pattern/drift", "recovered_share")
    s_share = 100 * mean("new_fraud_pattern/scheduled", "recovered_share")
    d_days, s_days = days(rec_d), days(rec_s)
    d_retrains = mean("new_fraud_pattern/drift", "retrains")
    s_retrains = mean("new_fraud_pattern/scheduled", "retrains")
    false_retrains = mean("control/drift", "retrains")
    weekly_control = mean("control/scheduled", "retrains")
    if d_days or s_days:
        timing = f" within {d_days or 'the run'}, versus {s_days or 'never'} for weekly retraining"
    else:
        timing = (
            ", the same as weekly retraining "
            f"({s_share:.0f}%); neither got back to 95% of the pre-drift catch before "
            "the run ended"
        )
    text = (
        f"When a new fraud pattern appeared, drift-triggered retraining recovered "
        f"{d_share:.0f}% of the lost fraud catch{timing}. It needed {d_retrains:.1f} retrains "
        f"instead of {s_retrains:.0f}, and {false_retrains:.0f} false retrains on the no-drift "
        f"control (weekly retraining: {weekly_control:.0f})."
    )
    return {
        "text": text,
        "fraud_caught_after_drift": {
            p: mean(f"new_fraud_pattern/{p}", "recall_post") for p in ("drift", "scheduled", "none")
        },
        "control_retrains": {
            p: mean(f"control/{p}", "retrains") for p in ("drift", "scheduled", "none")
        },
    }


def plotly_page(set_name: str) -> None:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    by = charts._by(results.load_runs(set_name))
    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=[charts.SCENARIO_LABEL[s] for s in charts.SCENARIOS],
        shared_yaxes=True,
        vertical_spacing=0.12,
    )
    for k, sc in enumerate(charts.SCENARIOS):
        row, col = k // 2 + 1, k % 2 + 1
        for policy in theme.POLICY_ORDER:
            runs = by.get((sc, policy))
            if not runs:
                continue
            style = theme.POLICY_STYLE[policy]
            days, m = charts._rolling_matrix(runs)
            dash = {"-": "solid", "--": "dash", ":": "dot"}[style["linestyle"]]
            h = style["color"].lstrip("#")
            rgba = f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},0.15)"
            for bound, fill in ((m.min(0), None), (m.max(0), "tonexty")):
                fig.add_trace(
                    go.Scatter(
                        x=days,
                        y=100 * bound,
                        mode="lines",
                        line={"width": 0},
                        fill=fill,
                        fillcolor=rgba,
                        legendgroup=policy,
                        showlegend=False,
                        hoverinfo="skip",
                    ),
                    row=row,
                    col=col,
                )
            fig.add_trace(
                go.Scatter(
                    x=days,
                    y=100 * m.mean(0),
                    mode="lines",
                    name=style["label"],
                    line={"color": style["color"], "width": 3, "dash": dash},
                    legendgroup=policy,
                    showlegend=k == 0,
                    customdata=100 * np.stack([m.min(0), m.max(0)], axis=1),
                    hovertemplate="day %{x}<br>mean %{y:.1f}% caught"
                    "<br>seeds %{customdata[0]:.1f}% to %{customdata[1]:.1f}%"
                    "<extra>%{fullData.name}</extra>",
                ),
                row=row,
                col=col,
            )
    fig.update_layout(
        title="Fraud caught at the 1% budget (7-day rolling): band = min to max across seeds",
        template="none",
        paper_bgcolor=theme.BG,
        plot_bgcolor=theme.PANEL,
        font={"family": "Inter, sans-serif", "color": theme.TEXT},
        height=820,
        legend={"orientation": "h", "y": -0.08},
        hoverlabel={
            "bgcolor": theme.PANEL,
            "font": {"color": theme.TEXT},
            "bordercolor": theme.BORDER,
        },
        margin={"l": 60, "r": 20, "t": 80, "b": 60},
    )
    fig.update_yaxes(range=[30, 100], gridcolor=theme.BORDER, ticksuffix="%")
    fig.update_xaxes(gridcolor=theme.BORDER, title_text="simulated day", row=2)
    html = fig.to_html(
        include_plotlyjs="cdn", full_html=True, config={"displaylogo": False, "responsive": True}
    )
    html = html.replace(
        "<head>",
        "<head><title>Tideline: interactive comparison</title>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<style>body{{background:{theme.BG};margin:0}}</style>",
        1,
    )
    (SITE / "compare.html").write_text(html, encoding="utf-8")


def build(set_name: str = "test") -> list[str]:
    done = []
    path = results.write(set_name)
    summary = json.loads(path.read_text())
    done.append(str(path.relative_to(REPO_ROOT)))
    h = headline(summary)
    (REPO_ROOT / "results" / "headline.json").write_text(json.dumps(h, indent=2))
    out = []
    out += charts.fraud_caught_over_time(summary, set_name)
    out += charts.detect_and_recover(summary, set_name)
    out += charts.retrains(summary, set_name)
    out += charts.drift_at_detection(set_name)
    parity_files = sorted((REPO_ROOT / "results" / "fullloop").glob("*/parity.json"))
    out += charts.feature_parity(parity_files) or []
    for s in ("dev", "test"):
        out += scenario_check.plot(s, seed=101 if s == "dev" else 201)
    done += [str(p.relative_to(REPO_ROOT)) for p in out]
    agreement.build()
    done.append("results/fullloop/agreement.md")
    site_build.build(set_name)
    (SITE / "data" / "headline.json").write_text(json.dumps(h, indent=2))
    shutil.copytree(REPO_ROOT / "assets" / "charts", SITE / "charts", dirs_exist_ok=True)
    shutil.copy(REPO_ROOT / "assets" / "logo.svg", SITE / "logo.svg")
    plotly_page(set_name)
    done.append("site/")
    return done
