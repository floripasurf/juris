"""SMTP email delivery for deadline alerts."""
from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from juris.alerts.deadline_alerts import AlertBatch, AlertLevel
from juris.core.observability import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AlertEmailConfig:
    """SMTP configuration for alert delivery."""

    smtp_host: str
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_address: str = ""
    to_addresses: list[str] = field(default_factory=list)
    use_tls: bool = True

    @property
    def is_configured(self) -> bool:
        """Check if SMTP is minimally configured."""
        return bool(self.smtp_host and self.from_address and self.to_addresses)


class AlertDelivery:
    """Send deadline alert emails via SMTP."""

    def __init__(self, config: AlertEmailConfig) -> None:
        self._config = config

    async def send_alert_batch(self, batch: AlertBatch) -> bool:
        """Send email with alert summary. Returns success."""
        if not self._config.is_configured:
            logger.warning("smtp_not_configured")
            return False

        if not batch.alerts:
            logger.debug("no_alerts_to_send", numero_cnj=batch.numero_cnj)
            return True

        subject, html_body = self._render_email(batch)

        try:
            self._send_smtp(subject, html_body)
            logger.info(
                "alert_email_sent",
                numero_cnj=batch.numero_cnj,
                alerts=len(batch.alerts),
                critical=batch.critical_count,
            )
            return True
        except Exception:
            logger.exception("alert_email_failed", numero_cnj=batch.numero_cnj)
            return False

    def _render_email(self, batch: AlertBatch) -> tuple[str, str]:
        """Render subject and HTML body for the alert email."""
        if batch.has_critical:
            subject = (
                f"[URGENTE] {batch.critical_count} alerta(s) critico(s)"
                f" — {batch.numero_cnj}"
            )
        else:
            subject = f"Alertas de prazo — {batch.numero_cnj}"

        rows = []
        for alert in batch.alerts:
            if alert.level == AlertLevel.CRITICAL:
                color = "#dc3545"
                icon = "&#x1F534;"
            elif alert.level == AlertLevel.WARNING:
                color = "#ffc107"
                icon = "&#x1F7E1;"
            else:
                color = "#6c757d"
                icon = "&#x26AA;"

            rows.append(
                f'<tr style="border-bottom:1px solid #eee;">'
                f'<td style="padding:8px;">{icon}</td>'
                f'<td style="padding:8px;color:{color};font-weight:bold;">'
                f"{alert.level.value.upper()}</td>"
                f'<td style="padding:8px;">{alert.prazo.rule.nome}</td>'
                f'<td style="padding:8px;">'
                f'{alert.prazo.data_limite.strftime("%d/%m/%Y")}</td>'
                f'<td style="padding:8px;">{alert.message}</td>'
                f"</tr>"
            )

        table_rows = "\n".join(rows)
        html = f"""\
<html>
<body style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;">
<h2>Alertas de Prazo</h2>
<p><strong>Processo:</strong> {batch.numero_cnj}<br>
<strong>Tribunal:</strong> {batch.tribunal}<br>
<strong>Data:</strong> {batch.generated_at.strftime("%d/%m/%Y")}</p>
<p><strong>Resumo:</strong> {batch.summary}</p>
<table style="width:100%;border-collapse:collapse;">
<tr style="background:#f8f9fa;">
<th style="padding:8px;text-align:left;"></th>
<th style="padding:8px;text-align:left;">Nivel</th>
<th style="padding:8px;text-align:left;">Prazo</th>
<th style="padding:8px;text-align:left;">Vencimento</th>
<th style="padding:8px;text-align:left;">Detalhe</th>
</tr>
{table_rows}
</table>
<p style="color:#6c757d;font-size:0.9em;margin-top:20px;">
Enviado automaticamente pelo sistema Juris.
</p>
</body>
</html>"""

        return subject, html

    def _send_smtp(self, subject: str, html_body: str) -> None:
        """Send email via SMTP (synchronous)."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._config.from_address
        msg["To"] = ", ".join(self._config.to_addresses)

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        server = smtplib.SMTP(self._config.smtp_host, self._config.smtp_port)
        try:
            if self._config.use_tls:
                server.starttls()

            if self._config.smtp_user and self._config.smtp_password:
                server.login(self._config.smtp_user, self._config.smtp_password)

            server.sendmail(
                self._config.from_address,
                self._config.to_addresses,
                msg.as_string(),
            )
        finally:
            server.quit()
