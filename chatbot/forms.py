from django import forms
from .models import Chatbot, ChatbotContact, ChatbotMedia

class ChatbotForm(forms.ModelForm):
    class Meta:
        model = Chatbot
        fields = '__all__'
        exclude = ['user', 'conversations_count', 'last_reset_date', 'current_tokens_used']
        
        widgets = {
            # --- Configuração Básica ---
            'instance': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            
            # --- Identidade da Empresa ---
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'company_website': forms.URLInput(attrs={'class': 'form-control'}),
            'sector': forms.TextInput(attrs={'class': 'form-control'}),
            'segment': forms.Select(attrs={'class': 'form-select'}),
            'company_summary': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Resumo da empresa...'}),
            'conversation_tone': forms.Select(attrs={'class': 'form-select'}),
            'business_hours': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Segunda a Sexta, 09h às 18h...'}),

            # --- Transferência ---
            'transf_1_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'transf_1_label': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'transf_1_number': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'transf_2_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'transf_2_label': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'transf_2_number': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'transf_3_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'transf_3_label': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'transf_3_number': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'transf_4_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'transf_4_label': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'transf_4_number': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'transf_5_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'transf_5_label': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'transf_5_number': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),

            # --- IA e Cérebro ---
            'ai_provider': forms.Select(attrs={'class': 'form-select'}),
            'model_name': forms.TextInput(attrs={'class': 'form-control'}),
            'api_key': forms.TextInput(attrs={'class': 'form-control'}),
            'context': forms.Textarea(attrs={'rows': 8, 'class': 'form-control'}),
            'skills': forms.Textarea(attrs={'rows': 8, 'class': 'form-control'}),
            'extra_instructions': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),

            # --- Memória (NOVO) ---
            'use_history': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'history_limit': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Padrão: 10'}),

            # --- Comportamento ---
            'trigger_on_groups': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'trigger_on_unknown': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'simulate_typing': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_audio_response': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_media_response': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'typing_time_min': forms.NumberInput(attrs={'class': 'form-control'}),
            'typing_time_max': forms.NumberInput(attrs={'class': 'form-control'}),

            # --- Limites ---
            'token_usage_type': forms.Select(attrs={'class': 'form-select'}),
            'token_limit': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if self.user:
            qs = self.user.instances.all()
            if not self.instance.pk:
                qs = qs.filter(chatbot_config__isnull=True)
            if self.instance.pk and self.instance.instance:
                from django.db.models import Q
                qs = self.user.instances.filter(Q(chatbot_config__isnull=True) | Q(pk=self.instance.instance.pk))
            self.fields['instance'].queryset = qs
        
        for field_name, field in self.fields.items():
            if 'class' not in field.widget.attrs:
                if isinstance(field.widget, (forms.TextInput, forms.Textarea, forms.NumberInput, forms.URLInput)):
                    field.widget.attrs.update({'class': 'form-control'})
                elif isinstance(field.widget, forms.Select):
                    field.widget.attrs.update({'class': 'form-select'})
                elif isinstance(field.widget, forms.CheckboxInput):
                    field.widget.attrs.update({'class': 'form-check-input'})

class ChatbotMediaForm(forms.ModelForm):
    class Meta:
        model = ChatbotMedia
        # Adicionado 'send_rules' para permitir a edição das regras de envio
        fields = ['file', 'media_type', 'description', 'send_rules', 'is_accessible_by_ai']
        widgets = {
            'file': forms.FileInput(attrs={'class': 'form-control'}),
            'media_type': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'O que é este arquivo? (Ex: Tabela de Preços)'}),
            'send_rules': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Quando enviar? (Ex: Quando o cliente pedir preço ou catálogo)'}),
            'is_accessible_by_ai': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class ChatbotContactForm(forms.ModelForm):
    class Meta:
        model = ChatbotContact
        fields = ['push_name', 'notes', 'is_blocked']
        widgets = {
            'push_name': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_blocked': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }