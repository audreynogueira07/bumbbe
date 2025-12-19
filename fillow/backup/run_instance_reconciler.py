import time
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from fillow.models import Instance
from fillow.services import NodeBridge, reconcile_instance

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Roda um reconciliador contínuo: sincroniza token/status do Node e tenta (re)iniciar sessões desconectadas."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=10, help="Intervalo (segundos) entre varreduras.")
        parser.add_argument("--sleep-per-instance", type=float, default=0.2, help="Pausa curta entre instâncias para não sobrecarregar o Node.")
        parser.add_argument("--start-if-missing", action="store_true", help="Se setado, tenta /sessions/start para sessões ausentes/desconectadas.")
        parser.add_argument("--only-stale-seconds", type=int, default=0, help="Se >0, só reconcilia instâncias sem update há X segundos.")
        parser.add_argument("--max", type=int, default=0, help="Se >0, limita quantas instâncias reconcilia por ciclo.")

    def handle(self, *args, **opts):
        interval = max(3, int(opts["interval"]))
        sleep_per_instance = max(0.0, float(opts["sleep_per_instance"]))
        start_if_missing = bool(opts["start_if_missing"])
        only_stale_seconds = int(opts["only_stale_seconds"] or 0)
        max_n = int(opts["max"] or 0)

        bridge = NodeBridge()

        self.stdout.write(self.style.SUCCESS(
            f"[reconciler] Iniciado. interval={interval}s, start_if_missing={start_if_missing}, only_stale_seconds={only_stale_seconds}, max={max_n or '∞'}"
        ))

        while True:
            try:
                qs = Instance.objects.all().order_by("updated_at")
                if only_stale_seconds > 0:
                    cutoff = timezone.now() - timezone.timedelta(seconds=only_stale_seconds)
                    qs = qs.filter(updated_at__lt=cutoff)

                if max_n > 0:
                    qs = qs[:max_n]

                count = 0
                for inst in qs:
                    try:
                        res = reconcile_instance(inst, bridge=bridge, start_if_missing=start_if_missing)
                        logger.info(
                            "[reconciler] %s status=%s token=%s started=%s synced=%s",
                            inst.session_id,
                            res.get("status"),
                            "YES" if res.get("token") else "NO",
                            res.get("started"),
                            res.get("synced"),
                        )
                        count += 1
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[reconciler] erro na instância %s: %s", getattr(inst, "session_id", "?"), e)

                    if sleep_per_instance:
                        time.sleep(sleep_per_instance)

                logger.info("[reconciler] ciclo concluído. instâncias=%d", count)

            except Exception as e:  # noqa: BLE001
                logger.exception("[reconciler] erro no ciclo: %s", e)

            time.sleep(interval)
