# encoding: utf-8
import json, logging #Librerias standar de Python
from flask import Flask, request, make_response, render_template #Librerias FLASK
import requests #Libreria para hacer requests HTTP
import google.cloud.logging #Servicio loggin de GCP
import re
from datetime import datetime
import google.cloud.storage #Servicio storage de GCP

import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import tensorflow as tf
from tensorflow import keras


app = Flask(__name__)

VERIFY_TOKEN='235689124578' #para validar acceso de verificacion de Facebook
ACCESS_TOKEN='EAAIfEqUZB0LUBAGE0uSu10rZAuQhqmmEMvlVgBJgGTUewwgb2GqYr3CAtxkqWhOVgTJHAMp3yYfZCSZCo5IyGEIUqMjuQQ7XTQ6wjsZAlEl52u7hFPrqRkN12soVUwO6lBxzwbMXOmOTltqE1OfIWYgYjZAOl22Y2N8aZCKxcyYyvZBGK7uzJ67GczJ2BhkiuoUZD'

# Validaciones del servicio loggin de GCP
client = google.cloud.logging.Client()
client.setup_logging()
# --------------------------------------------------------------------------------
invocacion=True
pregunta=0
#Carga del modelo previamente entrenado
#logging.error("Carga de modelo")

model = keras.models.load_model('model4.h5')
# --------------------------------------------------------------------------------
# Inicializa el cliente de GCS.
#logging.error("Iniciando cliente de Storage")
clientS = google.cloud.storage.Client()
bucket = None
# Nombre del bucket y del archivo.
bucket_name = "bucket_glucosa_bot"
file_name = "historia.json"
# Lista temporal para registrar datos para prediccion
lista=[]
# Lista temporal para registrar historia
lista_hist=[]
historia={}
df_historia=pd.DataFrame(historia)
nfilas=0
#----------------------------------------------------------------------------------

# Clase principal
class Main:
    def __init__(self):
        #super(Main).__init__()
        logging.warning("Instanciando bot")

    # Funcion para gestionar peticiones GET en la ruta /
    @staticmethod
    @app.route('/', methods=['GET']) # decorator
    def get(): 
        mode = request.args.get("hub.mode") #obtetiendo el tipo de peticion 
        if mode == "subscribe": #si es del tipo "suscribe"
            challenge = request.args.get("hub.challenge") #cargando valor de respuesta que espera Facebook
            verify_token = request.args.get("hub.verify_token") #leyendo token enviado para su comparacion
            if verify_token == VERIFY_TOKEN: 
                response = make_response(challenge) #si todo ok prepara la respuesta con la estructura apropiada
                response.headers['Content-Type'] = 'text/plain' 
                return response # envio de respuesta 
            else:
                return ("Error de Validacion") #error de token
        else: 
            return ("Ok") #envio de respuesta OK en caso que no se este validando Facebook

    # Funcion par gestionar peticiones POST en la ruta /
    @staticmethod
    @app.route('/', methods=['POST']) #decorator
    def post(): 
        if invocacion:
            pass
        data = request.get_json() #leyendo datos enviados por facebook 
        logging.info("Data obtenida desde Messenger: %r",data) #registrando lectura en el log del hosting
        if data['object']=='page': #validacion de la estructura de datos. Si es del tipo page continuamos
            for entry in data['entry']: #leer iterativamente la estructura de datos que manda Facebook en cada mensaje
                for messaging_event in entry['messaging']:
                    sender_id = messaging_event['sender']['id'] #captura del id del usuario que envia el mensaje
                    if messaging_event.get('message'): # Si es mensaje de texto simple
                        message = messaging_event['message']
                        message_text = messaging_event['message'].get('text','')
                        logging.info("Mensaje obtenido: %s",message_text) #registro en el log del hosting
                        bot_response(sender_id,message_text,tipo_respuesta= 'message')
                    if messaging_event.get('postback'): # Si es mensaje tipo Postback
                        message_text = messaging_event['postback']['payload']
                        bot_response(sender_id,message_text,tipo_respuesta= 'postback')
                        logging.warning("Post-back: %s",message_text) #registrar en el log del hosting un mensaje del tipo post-back
        else:
            logging.warning("No es page. No procesado.") #si no es page no lo procesamos
        return "OK"
#------------------------------------------------------------------------------------------------------------------------------------
# Cargando la historia desde el bucket en GCP
def load_data():
    global historia
    global df_historia
    global nfilas
    global bucket
    logging.error("Iniciando obtencion de datos desde Storage")
    bucket = clientS.get_bucket(bucket_name)
    blob = google.cloud.storage.Blob(file_name, bucket)
    try:
        # cargando BD .json como dict
        historia = json.loads(blob.download_as_text())
        df_historia=pd.DataFrame(historia)
        nfilas=len(df_historia)
        logging.warning("Data obtenida desde Storage %r",nfilas)
    except Exception as e:
        logging.error("Error cargando BD: Historia.json")
        historia = {}    

# Almacena los datos en el bucket de GCS.
def save_data():
    global bucket
    global file_name
    global df_historia
    historia_str = df_historia.to_json()
    historia_json = json.loads(historia_str)
    blob = google.cloud.storage.Blob(file_name, bucket)
    try:
        blob.upload_from_string(json.dumps(historia_json))
        logging.warning("Datos guardados en BD: Historia.json")
    except Exception as e:
        logging.error("Error al guardar datos en BD: Historia.json")

# funciones complementarias
def a_entero(cadena):
    match = re.findall(r"\d+", cadena)
    if match: return int(match[0])
    else: return None

def a_real(cadena):
    match1 = re.findall(r'\d+\.\d+', cadena)
    match2 = re.findall(r'\d+', cadena)
    if match1: 
        return float(match1[0])
    elif match2:
        return float(match2[0])
    else:
        return None

def validacion_sn(cadena):
    valor = {'S': 1, 'SI': 1, 'N': 0, 'NO': 0}
    return valor.get(cadena.upper(), -1)

def salir(cadena):
    if cadena.lower().find('salir') != -1 or cadena.lower().find('terminar') != -1 or cadena.lower().find('exit') != -1:
        return True
    else: 
        return False

possible_answers=['Si','No']

# Funcion para enviar mensaje al usuario de Facebook indicado en el parametro recipient_id
def send_message(recipient_id, message_text,tipo):
    logging.info("Enviando mensaje a %r: %s", recipient_id, message_text) # Registro de actividad en el log
    # Estructura del mensaje de respuesta
    headers = {
        "Content-Type": "application/json"
    }
    if tipo == 'postback':
        message = get_postback_buttons_message(message_text, possible_answers)
    elif tipo == 'message':
        message = {"text": message_text}

    raw_data = {
        "recipient": {
            "id": recipient_id
        },
        "messaging_type": "RESPONSE",
        "message": message
    }
    data = json.dumps(raw_data) #conversion al tipo de dato apropiado para el envio a Facebook
    r = requests.post("https://graph.facebook.com/me/messages?access_token=%s" % ACCESS_TOKEN, headers=headers, data=data) #envio de datos usando HTTP
    if r.status_code != 200: # si es distinto de 200 entonces -> error
        logging.error("Error %r enviando mensaje: %s", r.status_code, r.content) #registrar en el log del hosting
        return "Error"
    else: #si todo ok
        return "OK"



def get_postback_buttons_message(message_text, possible_answers):
    buttons = []
    for answer in possible_answers:
        buttons.append({
            "type": "postback",
            "title": answer,
            "payload": answer           
        })

    return get_buttons_template(message_text, buttons)

def get_buttons_template(message_text, buttons):
    return {
        "attachment": {
            "type": "template",
            "payload": {
                "template_type": "button",
                "text": message_text,
                "buttons": buttons
            }
        }
    }

def get_url_buttons_message(message_text):
    # urls = message_text.split()
    elements = []
    elements.append({
        "url": message_text
    })
    return get_open_graph_template(elements)

def get_open_graph_template(elements):
    return {
        "attachment": {
            "type": "template",
            "payload": {
                "template_type": "open_graph",
                "elements": elements
            }
        }
    }  

#--------Implementacion del Bot----------
def bot_response(recipient_id, message_text,tipo_respuesta):
    global invocacion
    global pregunta
    global lista
    global lista_hist
    global df_historia
    global nfilas
    response_bot = ''
    if invocacion and tipo_respuesta=='message':
        response_bot='Bienvenido! Soy tu asistente virtual y juntos estimaremos tus niveles de glucosa en la sangre. ¿Estas listo?'
        invocacion = False
        tipo_respuesta = 'postback'
    elif tipo_respuesta=='postback':
        if pregunta == 0:
            tipo_respuesta='message'
            if message_text=='Si': 
                # Inicializando lista
                load_data()
                ahora = datetime.now()
                lista_hist.append(recipient_id) # Id de usuario de messenger
                lista_hist.append(ahora.strftime('%d/%m/%Y')) # Fecha de sesion
                lista_hist.append(ahora.strftime('%H:%M')) # Hora de sesion
                df_usuario=df_historia.loc[df_historia['id_usuario']==recipient_id]
                df_usuario.reset_index(drop=True,inplace=True)
                if len(df_usuario)>0:
                    response_bot='Veo que ya nos ha visitado antes. En su ultimo reporte su indice glucosa fue:  '+str(round(df_usuario.loc[len(df_usuario)-1]['glucosa'],2))
                    send_message(recipient_id,message_text=response_bot, tipo = tipo_respuesta)    
                response_bot = 'Comencemos. Por favor responde las siguientes preguntas:'
                send_message(recipient_id,message_text=response_bot, tipo = tipo_respuesta)
                pregunta = 1
                response_bot = '1. Cual es tu edad?'#+str(pred[0][0])
            else: # si presionan NO
                response_bot='Ok. Cuando estes listo me lo haces saber y comenzamos. Gracias'
                invocacion = True
        # para las preguntas que deben ser respondidas con un SI o un NO
        elif pregunta == 7: # 7. Has tenido eventos de sudoraciones anormales recientenemte?
            sudor = validacion_sn(message_text)
            if sudor > -1:
                lista.append(sudor)
                lista_hist.append(sudor)
                response_bot = '8. Recientemente has sufrido de temblores inusuales? (Si/No)'
                pregunta = 8
            else:
                response_bot = 'Error pregunta 7'
                pregunta = 7
        elif pregunta == 8: #8. Recientemente has sufrido de temblores inusuales?
            temblor = validacion_sn(message_text)
            if temblor >-1:
                lista.append(temblor)
                lista_hist.append(temblor)
                response_bot = '9. Has sido previamente diagnosticado(a) de diabetes? (Si/No)'
                pregunta = 9
            else:
                response_bot = 'Error pregunta 8'
                pregunta = 8
        elif pregunta == 9:
            diabet = validacion_sn(message_text)
            if diabet >-1:
                lista.append(diabet)
                lista_hist.append(diabet)
                response_bot = 'Muchas gracias por tu colaboracion. Ahora realizare los calculos necesarios para estimar el valor de Glucosa en tu sangre...'
                tipo_respuesta='message'
                send_message(recipient_id,message_text=response_bot, tipo = tipo_respuesta)
                pregunta = 0
                invocacion=True
                pred=round(predictor(lista),2)
                response_bot='Glucosa: '+str(pred)
                send_message(recipient_id,message_text=response_bot, tipo = tipo_respuesta)
                # grabar en storage
                lista_hist.append(pred)
                df_historia.loc[nfilas] = lista_hist
                save_data()
                # Emitir diagnostico
                response_bot=diagnostico(pred)
                send_message(recipient_id,message_text=response_bot, tipo = tipo_respuesta)
                # reiniciar variables
                lista=[]
                lista_hist=[]
                response_bot='Proceso terminado. Gracias por su participacion'
                
                tipo_respuesta='message'
                # Fin del cuestionario
            else:
                response_bot = 'Error pregunta 9'
                pregunta = 9
    elif tipo_respuesta == 'message':
        if pregunta == 1: # 1. Cual es tu edad?
            if not(salir(message_text)):
                edad = a_entero(message_text)
                if edad != None:
                    if edad>150 or edad<0:
                        response_bot='El valor de la edad esta fuera de rango. Ingresa un valor entre 0 y 150'
                        pregunta=1
                    else:
                        lista.append(edad)
                        lista_hist.append(edad)
                        response_bot = '2. Cual es tu presion arterial Diastolica (conocida como presion minima)?'
                        pregunta = 2
                else:
                    response_bot = 'Por favor ingresa tu edad expresada usando numero enteros. Ejemplo: 29. Intentalo nuevamente.'
                    pregunta = 1
            else:
                invocacion = True
                pregunta = 0
                lista=[]
                lista_hist=[]
                response_bot='Terminado. Cuando estes preparado me lo haces saber y comenzamos. Gracias'
        elif pregunta == 2: # 2. Cual es tu presion arterial Diastolica (conocida como presion minima)?
            if not(salir(message_text)):
                pDiast = a_entero(message_text)
                if pDiast != None:
                    if pDiast<20 or pDiast>150:
                        response_bot='El valor de la presion diastólica esta fuera de rango. Ingresa un valor entre 20 y 150'
                        pregunta=2
                    else:
                        lista.append(pDiast)
                        lista_hist.append(pDiast)
                        response_bot = '3. Cual es tu presion arterial Sistolica (conocida como presion maxima)?'
                        pregunta = 3
                else:
                    response_bot = 'Ingreso erroneo. La presión diastólica es la presión arterial mínima que se produce en las arterias cuando el corazón se relaja entre latidos. Se expresa como un numero entero. Ejemplo: 80. Intentalo nuevamente.'
                    pregunta = 2
            else:
                invocacion = True
                pregunta = 0
                lista=[]
                lista_hist=[]
                response_bot='Terminado. Cuando estes preparado me lo haces saber y comenzamos. Gracias'
        elif pregunta == 3: # 3. Cual es tu presion arterial Diastolica (conocida como presion minima)?
            if not(salir(message_text)):
                pSist = a_entero(message_text)
                if pSist != None:
                    if pSist<40 or pSist>260:
                        response_bot='El valor de la presion sistólica esta fuera de rango. Ingresa un valor entre 40 y 260'
                        pregunta=3
                    else:
                        lista.append(pSist)
                        lista_hist.append(pSist)
                        response_bot = '4. Ahora necesito conocer tu frecuencia cardiaca (valor en reposo)'
                        pregunta = 4
                else: 
                    response_bot = 'Ingreso incorrecto. La presión sistólica es la presión arterial máxima que se produce en las arterias cuando el corazón se contrae y bombea sangre al cuerpo. Se deb expresar como un numero entero. Ejemplo: 120. Intentalo nuevamente.'
                    pregunta = 3
            else:
                invocacion = True
                pregunta = 0
                lista=[]
                lista_hist=[]
                response_bot='Terminado. Cuando estes preparado me lo haces saber y comenzamos. Gracias'
        elif pregunta == 4: #4. Ahora necesito conocer tu frecuencia cardiaca (valor en reposo)
            if not(salir(message_text)):
                frec = a_entero(message_text)
                if frec != None:
                    if frec<30 or frec>290:
                        response_bot='El valor de la frecuencia cardiaca esta fuera de rango. Ingresa un valor entre 30 y 290'
                        pregunta=4
                    else:
                        lista.append(frec)
                        lista_hist.append(frec)
                        response_bot = '5. Ingresa por favor tu temperatura corporal, expresada en °C'
                        pregunta = 5
                else:
                    response_bot = 'Error en el ingreso de la frecuencia cardiaca. La frecuencia cardiaca es el número de veces que el corazón late en un minuto. Se debe expresar coon un numero entero. Ejemplo: 85. Intentalo nuevamente.'
                    pregunta = 4
            else:
                invocacion = True
                pregunta = 0
                lista=[]
                lista_hist=[]
                response_bot='Terminado. Cuando estes preparado me lo haces saber y comenzamos. Gracias'
        elif pregunta == 5: # 5. Ingresa por favor tu temperatura corporal, expresada en °C
            if not(salir(message_text)):
                temper = a_real(message_text)
                if temper != None:
                    if temper<35 or temper>42:
                        response_bot = 'Error, la temperatura ingresada esta fuera del rango aceptado. Debe ser mayor a 35 °C y menor a 43°C. Intentalo nuevamente.'
                        pregunta = 5
                    else:
                        temper =  32 + temper * 1.8 #Convierte °C en °F
                        lista.append(temper)
                        lista_hist.append(temper)
                        response_bot = '6. Voy a necesitar conocer tu indice de saturacion de oxigeno SPO2'
                        pregunta = 6
                else:
                    response_bot = 'Hubo un error en los datos ingresados. Intentalo nuevamente.'
                    pregunta = 5
            else:
                invocacion = True
                pregunta = 0
                lista=[]
                lista_hist=[]
                response_bot='Terminado. Cuando estes preparado me lo haces saber y comenzamos. Gracias'
        elif pregunta == 6: # 6. Voy a necesitar conocer tu indice de saturacion de oxigeno SPO2
            if not(salir(message_text)):
                spo2 = a_entero(message_text)
                if spo2 != None:
                    if spo2<70 or spo2>100:
                        response_bot='El valor de la saturacion de oxigeno en la sangre esta fuera de rango. Ingresa un valor entre 70 y 100'
                        pregunta=6
                    else:
                        lista.append(spo2)
                        lista_hist.append(spo2)
                        response_bot = '7. Has tenido eventos de sudoraciones anormales recientenemte? (Si/No)'
                        tipo_respuesta = 'postback'
                        pregunta = 7
                else:
                    response_bot = 'No se puede procesar la informacion. La saturacion de oxigeno en la sangre debe expresarse como un nuemro entero. Ejemplo: 98. Intentalo de nuevo.'
                    pregunta = 6
            else:
                invocacion = True
                pregunta = 0
                lista=[]
                lista_hist=[]
                response_bot='Terminado. Cuando estes preparado me lo haces saber y comenzamos. Gracias'

    send_message(recipient_id,message_text = response_bot, tipo = tipo_respuesta)

#------------------
def diagnostico(pred):
    if pred<20:
        respuesta='Tus niveles de glucosa en la sangre estan muy bajos. Es probable que experimente síntomas graves de hipoglucemia, como convulsiones o pérdida del conocimiento.'
    elif pred<30:
        respuesta='Tus niveles de glucosa en la sangre estan muy bajos y probablemente provocará síntomas graves de hipoglucemia como confusión o pérdida del conocimiento.'
    elif pred<40:
        respuesta='Tus niveles de glucosa en la sangre estan muy bajos y probablemente provocará síntomas de hipoglucemia como sudoración, mareo y temblores.'
    elif pred<70:
        respuesta='Tus niveles de glucosa en la sangre estan bajos y puede provocar síntomas moderados de hipoglucemia como sudoración, mareo y temblores.'
    elif pred <100:
        respuesta='Buenas noticias, tus niveles de glucosa en la sangre estan en un rango normal.'
    elif pred<129:
        respuesta='Alerta!, tus niveles de glucosa en la sangre estan por encima del rango saludable y debe considerarse como pre-diabetes.'
    else:    
        respuesta='Alerta!, tus niveles de glucosa en la sangre estan por muy por encima del rango saludable y se considera como diabetes.'
    return respuesta
#------------------
def predictor(parametros):
    global model
    # Carga de Dataset desde bucket GCP 
    df = pd.read_csv('https://storage.googleapis.com/bucket_glucosa_bot/glucosa.csv',delimiter=';',encoding='utf-8')
    df['diabetic'] = df['diabetic'].replace('D', 1).replace('N', 0)
    X = df.drop('glucose', axis=1)
    y = df['glucose']
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
    # Convertir los datos a tensores
    X_train = tf.convert_to_tensor(X_train.values)
    y_train = tf.convert_to_tensor(y_train.values)
    #Estandarizando entradas
    sc = StandardScaler()
    X_train = sc.fit_transform(X_train)    
    # Hacer predicciones con el modelo
    x_input = np.array(parametros).reshape(1,-1)
    sc_input=sc.transform(x_input)
    pred = model.predict(sc_input)    
    return pred[0][0]

# Pagina de politicas de privacidad de datos
# requerimiento de Facebook para poder habilitar los servicios basicos
# los requerimientos avanzados requieren mas verificaciones aun pendientes
@app.route('/privacy_policies')
def privacy_policies():
    return render_template('policies.html')


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)
# [END gae_flex_quickstart]