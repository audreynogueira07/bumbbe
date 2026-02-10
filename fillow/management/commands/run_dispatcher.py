import time

from django.core.management.base import BaseCommand

from ...broadcast_services import process_dispatch_queue


class Command(BaseCommand):
    help = "Processa fila do disparador de WhatsApp."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Executa apenas uma rodada e sai.")
        parser.add_argument("--max-items", type=int, default=20, help="Máximo de itens por rodada.")
        parser.add_argument("--sleep", type=int, default=5, help="Segundos entre rodadas (modo loop).")

    def handle(self, *args, **options):
        once = options["once"]
        max_items = max(1, min(500, int(options["max_items"])))
        sleep_sec = max(1, int(options["sleep"]))

        if once:
            result = process_dispatch_queue(max_items=max_items)
            self.stdout.write(self.style.SUCCESS(f"Dispatch result: {result}"))
            return

        self.stdout.write(self.style.SUCCESS("Dispatcher em loop iniciado. Ctrl+C para parar."))
        while True:
            result = process_dispatch_queue(max_items=max_items)
            self.stdout.write(f"Dispatch result: {result}")
            time.sleep(sleep_sec)
