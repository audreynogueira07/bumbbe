from django import forms
from .models import WordpressBot, WordpressMedia

class WordpressBotForm(forms.ModelForm):
    class Meta:
        model = WordpressBot
        fields = '__all__'
        exclude = ['user', 'api_secret', 'created_at', 'updated_at']
        
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'company_website': forms.URLInput(attrs={'class': 'form-control'}),
            'company_summary': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'business_hours': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'conversation_tone': forms.Select(attrs={'class': 'form-select'}),
            'ai_provider': forms.Select(attrs={'class': 'form-select'}),
            'model_name': forms.TextInput(attrs={'class': 'form-control'}),
            'api_key': forms.TextInput(attrs={'class': 'form-control'}),
            'context': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'skills': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'use_history': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'history_limit': forms.NumberInput(attrs={'class': 'form-control'}),
        }

class WordpressMediaForm(forms.ModelForm):
    class Meta:
        model = WordpressMedia
        fields = ['file', 'media_type', 'description', 'send_rules']
        widgets = {
            'file': forms.FileInput(attrs={'class': 'form-control'}),
            'media_type': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'send_rules': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }