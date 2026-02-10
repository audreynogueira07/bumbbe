from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.urls import reverse
from django.views.generic import TemplateView

from .models import (
    DispatchCampaign,
    DispatchCampaignQueueItem,
    DispatchContactGroup,
    DispatchMessageTemplate,
    Instance,
    MediaFile,
)


class DispatchDashboardManagerView(LoginRequiredMixin, TemplateView):
    template_name = "fillow/pages/dispatch_manager.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        templates_qs = DispatchMessageTemplate.objects.all()
        groups_qs = DispatchContactGroup.objects.all()
        campaigns_qs = DispatchCampaign.objects.all()
        connected_instances_qs = Instance.objects.filter(status="CONNECTED")

        agg = campaigns_qs.aggregate(
            total_planned=Sum("total_planned"),
            total_sent=Sum("total_sent"),
            total_failed=Sum("total_failed"),
            total_recipients=Sum("total_recipients"),
        )

        summary = {
            "templates_count": templates_qs.count(),
            "groups_count": groups_qs.count(),
            "campaigns_count": campaigns_qs.count(),
            "connected_instances_count": connected_instances_qs.count(),
            "total_planned": agg.get("total_planned") or 0,
            "total_sent": agg.get("total_sent") or 0,
            "total_failed": agg.get("total_failed") or 0,
            "total_recipients": agg.get("total_recipients") or 0,
        }

        media_detail_pattern = reverse(
            "fillow:dispatch_media_detail",
            kwargs={"media_id": "00000000-0000-0000-0000-000000000000"},
        ).replace("00000000-0000-0000-0000-000000000000", "{id}")

        ctx.update(
            {
                "summary": summary,
                "connected_instances": connected_instances_qs.order_by("name")[:200],
                "instances": Instance.objects.all().order_by("name")[:500],
                "media_files": MediaFile.objects.filter(owner=self.request.user).order_by("-created_at")[:200],
                "queue_status_choices": DispatchCampaignQueueItem.STATUS_CHOICES,
                "media_type_choices": MediaFile.MEDIA_TYPE_CHOICES,
                "dispatch_api": {
                    "templates": reverse("fillow:dispatch_templates"),
                    "groups": reverse("fillow:dispatch_groups"),
                    "campaigns": reverse("fillow:dispatch_campaigns"),
                    "queue_process": reverse("fillow:dispatch_queue_process"),
                    "media_list": reverse("fillow:dispatch_media_list"),
                    "media_upload": reverse("fillow:dispatch_media_upload"),
                    "media_detail_pattern": media_detail_pattern,
                },
            }
        )
        return ctx
