from __future__ import annotations

import mimetypes
from typing import Optional

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import MediaFile


ALLOWED_MEDIA_TYPES = {choice[0] for choice in MediaFile.MEDIA_TYPE_CHOICES}


class DispatchMediaBaseMixin:
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _serialize_media(obj: MediaFile, request=None) -> dict:
        file_url = obj.file.url if obj.file else ""
        if request is not None and file_url:
            file_url = request.build_absolute_uri(file_url)

        return {
            "id": str(obj.id),
            "original_name": obj.original_name,
            "media_type": obj.media_type,
            "mime_type": obj.mime_type,
            "file_size": obj.file_size,
            "file_url": file_url,
            "created_at": obj.created_at,
            "owner_id": obj.owner_id,
        }

    @staticmethod
    def _guess_media_type(uploaded_file) -> str:
        content_type = getattr(uploaded_file, "content_type", "") or ""
        guessed_mime = content_type or (mimetypes.guess_type(uploaded_file.name)[0] or "")
        guessed_mime = guessed_mime.lower()

        if guessed_mime.startswith("image/"):
            return "image"
        if guessed_mime.startswith("video/"):
            return "video"
        if guessed_mime.startswith("audio/"):
            return "audio"
        if "pdf" in guessed_mime:
            return "doc"

        return "doc"

    @staticmethod
    def _coerce_media_type(value: Optional[str], uploaded_file) -> str:
        media_type = (value or "").strip().lower()
        if not media_type:
            media_type = DispatchMediaBaseMixin._guess_media_type(uploaded_file)

        if media_type not in ALLOWED_MEDIA_TYPES:
            raise ValueError(f"media_type inválido. Use um de: {', '.join(sorted(ALLOWED_MEDIA_TYPES))}")
        return media_type


class DispatchMediaListView(DispatchMediaBaseMixin, APIView):
    """
    GET /api/internal/media/
    Lista arquivos de mídia para uso em templates de disparo.
    """

    def get_queryset(self, request):
        qs = MediaFile.objects.all().order_by("-created_at")
        if not request.user.is_staff:
            qs = qs.filter(owner=request.user)

        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(original_name__icontains=q)

        media_type = (request.query_params.get("media_type") or "").strip().lower()
        if media_type in ALLOWED_MEDIA_TYPES:
            qs = qs.filter(media_type=media_type)

        limit = request.query_params.get("limit")
        try:
            limit_n = min(max(int(limit), 1), 500) if limit else 200
        except Exception:
            limit_n = 200

        return qs[:limit_n]

    def get(self, request):
        items = [self._serialize_media(obj, request=request) for obj in self.get_queryset(request)]
        return Response({"results": items, "count": len(items)}, status=status.HTTP_200_OK)


class DispatchMediaUploadView(DispatchMediaBaseMixin, APIView):
    """
    POST /api/internal/media/upload/
    Upload de arquivo de mídia para templates.

    form-data:
      - file (obrigatório)
      - media_type (opcional: image|video|audio|doc)
      - original_name (opcional)
    """

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        uploaded = request.FILES.get("file")
        if not uploaded:
            return Response({"error": "Arquivo não enviado. Use o campo 'file'."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            media_type = self._coerce_media_type(request.data.get("media_type"), uploaded)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        original_name = (request.data.get("original_name") or "").strip() or uploaded.name
        mime_type = getattr(uploaded, "content_type", "") or (mimetypes.guess_type(uploaded.name)[0] or "")
        file_size = int(getattr(uploaded, "size", 0) or 0)

        media = MediaFile.objects.create(
            file=uploaded,
            original_name=original_name,
            media_type=media_type,
            mime_type=mime_type,
            file_size=file_size,
            owner=request.user,
        )

        return Response(self._serialize_media(media, request=request), status=status.HTTP_201_CREATED)


class DispatchMediaDetailView(DispatchMediaBaseMixin, APIView):
    """
    PATCH/DELETE /api/internal/media/<uuid:media_id>/
    """

    def _get_obj(self, request, media_id):
        obj = get_object_or_404(MediaFile, pk=media_id)
        if request.user.is_staff or obj.owner_id == request.user.id:
            return obj
        return None

    def patch(self, request, media_id):
        obj = self._get_obj(request, media_id)
        if obj is None:
            return Response({"error": "Sem permissão para alterar este arquivo."}, status=status.HTTP_403_FORBIDDEN)

        original_name = request.data.get("original_name")
        media_type = request.data.get("media_type")

        if original_name is not None:
            obj.original_name = str(original_name).strip() or obj.original_name

        if media_type is not None:
            media_type = str(media_type).strip().lower()
            if media_type not in ALLOWED_MEDIA_TYPES:
                return Response(
                    {"error": f"media_type inválido. Use um de: {', '.join(sorted(ALLOWED_MEDIA_TYPES))}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            obj.media_type = media_type

        obj.save(update_fields=["original_name", "media_type", "updated_at"])
        return Response(self._serialize_media(obj, request=request), status=status.HTTP_200_OK)

    def delete(self, request, media_id):
        obj = self._get_obj(request, media_id)
        if obj is None:
            return Response({"error": "Sem permissão para excluir este arquivo."}, status=status.HTTP_403_FORBIDDEN)

        try:
            if obj.file:
                obj.file.delete(save=False)
        except Exception:
            pass

        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
