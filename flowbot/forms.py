from django import forms
from .models import FlowBot, FlowMedia


class FlowBotForm(forms.ModelForm):
    class Meta:
        model = FlowBot
        fields = ("name", "active", "description")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Atendimento Loja X"}),
            "active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Opcional..."}),
        }


class FlowMediaForm(forms.ModelForm):
    class Meta:
        model = FlowMedia
        fields = ("file", "media_type", "title", "caption")
        widgets = {
            "file": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "media_type": forms.Select(attrs={"class": "form-select"}),
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Título (opcional)"}),
            "caption": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Legenda/descrição..."}),
        }
