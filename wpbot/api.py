import traceback
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from wpbot.engine import WordpressBotEngine
from wpbot.serializers import ChatRequestSerializer, ChatResponseSerializer
from .models import WordpressBot, WordpressApiErrorLog # Importe o novo modelo

class WordpressChatAPI(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        raw_data = str(request.data)
        ip = request.META.get('REMOTE_ADDR')
        
        try:
            serializer = ChatRequestSerializer(data=request.data)
            
            # Falha de Validação de Campos
            if not serializer.is_valid():
                WordpressApiErrorLog.objects.create(
                    request_data=raw_data,
                    error_message=f"Erro de Validação: {serializer.errors}",
                    ip_address=ip
                )
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            data = serializer.validated_data
            
            # 1. Autenticação do Bot
            try:
                bot = WordpressBot.objects.get(api_secret=data['api_secret'], active=True)
            except WordpressBot.DoesNotExist:
                WordpressApiErrorLog.objects.create(
                    request_data=raw_data,
                    error_message="API Secret Inválido ou Bot Inativo",
                    ip_address=ip
                )
                return Response({"error": "Invalid API Secret"}, status=status.HTTP_401_UNAUTHORIZED)
            
            # 2. Processamento (Engine)
            try:
                engine = WordpressBotEngine(bot)
                response_data = engine.process_input(
                    session_uuid=data['session_uuid'],
                    user_message=data.get('message', ''),
                    user_name=data.get('user_name'),
                    user_phone=data.get('user_phone')
                )
                
                resp_serializer = ChatResponseSerializer(data=response_data)
                if resp_serializer.is_valid():
                    return Response(resp_serializer.data)
                else:
                    raise Exception(f"Erro no Serializer de Resposta: {resp_serializer.errors}")

            except Exception as engine_err:
                # Erro interno durante o processamento da IA ou Banco
                WordpressApiErrorLog.objects.create(
                    bot=bot,
                    request_data=raw_data,
                    error_message=str(engine_err),
                    stack_trace=traceback.format_exc(),
                    ip_address=ip
                )
                return Response({"error": "Internal Processing Error"}, status=500)

        except Exception as e:
            # Erro crítico não mapeado
            WordpressApiErrorLog.objects.create(
                request_data=raw_data,
                error_message=f"Critical System Error: {str(e)}",
                stack_trace=traceback.format_exc(),
                ip_address=ip
            )
            return Response({"error": "System Failure"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)