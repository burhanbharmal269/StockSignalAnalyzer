"""ScoreExplanationBuilder — template-based, deterministic explanation generator.

Produces a human-readable list[str] from ScoreResult + component outputs.
No AI calls. No BUY / SELL / ORDER / TRADE terminology in output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.value_objects.component_output import ComponentOutput
    from core.domain.value_objects.score_context import ScoreContext
    from core.domain.value_objects.score_result import ScoreResult


class ScoreExplanationBuilder:
    """Builds a plain-English summary from scoring artefacts."""

    def build(
        self,
        result: ScoreResult,
        component_outputs: list[ComponentOutput],
        context: ScoreContext,
    ) -> list[str]:
        lines: list[str] = []

        # 1. Summary
        lines.append(self._summary_line(result))

        # 2. Data completeness
        avail = sum(1 for o in component_outputs if o.is_available)
        lines.append(
            f"Data: {avail}/{len(component_outputs)} components available "
            f"({result.data_completeness_pct:.0f}% completeness, "
            f"quality={result.score_quality})"
        )

        # 3. Regime context
        lines.append(
            f"Regime: {context.regime.value} "
            f"[{result.score_breakdown.regime_alignment}]"
        )

        if not result.is_eligible:
            lines.append(
                "Score not eligible for downstream processing "
                f"(direction={result.direction}, "
                f"completeness={result.data_completeness_pct:.0f}%)"
            )
            return lines

        # 4. Component contributions (available, descending by absolute contribution)
        available_outputs = [o for o in component_outputs if o.is_available]
        breakdown = result.score_breakdown
        breakdown_vals = breakdown.as_dict()
        contributions = [
            (o, breakdown_vals.get(o.component_name.lower(), 0.0))
            for o in available_outputs
        ]
        contributions.sort(key=lambda x: abs(x[1]) if isinstance(x[1], float) else 0, reverse=True)  # noqa: E501

        lines.append("Component evidence:")
        for output, contrib in contributions:
            contrib_str = (
                f"+{contrib:.1f}" if isinstance(contrib, float) and contrib >= 0
                else f"{contrib:.1f}"
            )
            lines.append(
                f"  [{output.direction:7s}] {output.component_name}: "
                f"{contrib_str} pts — {output.key_finding}"
            )

        # 5. Unavailable components
        unavailable = [o for o in component_outputs if not o.is_available]
        if unavailable:
            lines.append("Unavailable components:")
            for o in unavailable:
                lines.append(f"  {o.component_name}: {o.key_finding}")

        # 6. Penalties
        if result.penalties:
            lines.append(
                f"Penalties ({len(result.penalties)} applied, "
                f"total {result.total_penalty:+.1f} pts):"
            )
            for p in result.penalties:
                lines.append(f"  [{p.penalty_type}] {p.amount:+.1f}: {p.reason}")

        return lines

    # ------------------------------------------------------------------

    @staticmethod
    def _summary_line(result: ScoreResult) -> str:
        if not result.is_eligible:
            return (
                f"INELIGIBLE | direction={result.direction} | "
                f"conviction={result.direction_conviction:.2f} | "
                f"adjusted_score={result.adjusted_score:.1f}"
            )
        return (
            f"{result.direction} | "
            f"conviction={result.direction_conviction:.2f} | "
            f"raw={result.raw_score:.1f} → adjusted={result.adjusted_score:.1f} | "
            f"quality={result.score_quality}"
        )
