import socket
import threading
import multiprocessing
import os
from datetime import datetime
import urllib.parse
from pymongo import MongoClient
import json
import logging

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,  # Вивід логів у консоль
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

HOST = '0.0.0.0'
HTTP_PORT = 3000
SOCKET_PORT = 5000

# Функція для обробки HTTP-запитів
def handle_http(client_connection):
    try:
        # Читаємо дані з сокета
        request_data = b''
        while True:
            chunk = client_connection.recv(1024)
            if not chunk:
                break
            request_data += chunk
            # Перевіряємо, чи ми отримали всі заголовки (закінчуються на '\r\n\r\n')
            if b'\r\n\r\n' in request_data:
                break
        # Декодуємо отримані дані
        request_text = request_data.decode('utf-8')
        # Розділяємо заголовки та тіло
        headers_part, _, body = request_text.partition('\r\n\r\n')
        headers = headers_part.split('\r\n')
        first_line = headers[0]
        method, path, protocol = first_line.split()
        path = urllib.parse.unquote(path)

        # Логування запиту
        logging.info(f"Отримано {method} запит до {path}")

        # Отримуємо Content-Length з заголовків
        content_length = 0
        for header in headers:
            if header.startswith('Content-Length'):
                content_length = int(header.split(':')[1].strip())
                break

        # Перевіряємо, чи все тіло отримано
        body_bytes = body.encode('utf-8')
        if content_length > len(body_bytes):
            remaining = content_length - len(body_bytes)
            body_bytes += client_connection.recv(remaining)
            body = body_bytes.decode('utf-8')

        if method == 'GET':
            if path == '/' or path == '/index.html':
                serve_file(client_connection, 'templates/index.html', 'text/html')
            elif path == '/message.html' or path == '/message':
                serve_file(client_connection, 'templates/message.html', 'text/html')
            elif path == '/style.css':
                serve_file(client_connection, 'style.css', 'text/css')
            elif path == '/logo.png':
                serve_file(client_connection, 'logo.png', 'image/png')
            elif path.startswith('/static/'):
                file_path = path.lstrip('/')
                if os.path.exists(file_path):
                    mime_type = get_mime_type(file_path)
                    serve_file(client_connection, file_path, mime_type)
                else:
                    serve_404(client_connection)
            else:
                serve_404(client_connection)
        elif method == 'POST':
            if path == '/message':
                logging.info("Початок обробки POST-запиту")
                try:
                    # Парсимо параметри форми
                    logging.info(f"Отримано тіло запиту: {body}")
                    params = urllib.parse.parse_qs(body)
                    logging.info(f"Розібрані параметри: {params}")
                    username = params.get('username', [''])[0]
                    message = params.get('message', [''])[0]

                    # Відправка даних Socket-серверу та отримання відповіді
                    data = {'username': username, 'message': message}
                    response_status = send_to_socket_server(data)

                    if response_status == 'SUCCESS':
                        logging.info("Дані успішно відправлені Socket-серверу та збережені в базі даних")
                        # Формування відповіді клієнту про успіх
                        response_body = '''
                        <!DOCTYPE html>
                        <html lang="uk">
                        <head>
                            <meta charset="UTF-8">
                            <title>Повідомлення надіслано</title>
                        </head>
                        <body>
                            <h1>Дані успішно записані!</h1>
                            <a href="/message">Надіслати нове повідомлення</a>
                        </body>
                        </html>
                        '''
                        response = 'HTTP/1.1 200 OK\r\n'
                    else:
                        logging.error("Помилка при збереженні даних в базу даних")
                        # Формування відповіді клієнту про помилку
                        response_body = '''
                        <!DOCTYPE html>
                        <html lang="uk">
                        <head>
                            <meta charset="UTF-8">
                            <title>Помилка збереження</title>
                        </head>
                        <body>
                            <h1>Дані не можуть бути записані!</h1>
                            <a href="/message">Спробувати ще раз</a>
                        </body>
                        </html>
                        '''
                        response = 'HTTP/1.1 500 Internal Server Error\r\n'

                    # Додавання заголовків та відправка відповіді
                    response += 'Content-Type: text/html; charset=utf-8\r\n'
                    response += f'Content-Length: {len(response_body.encode("utf-8"))}\r\n'
                    response += 'Connection: close\r\n'
                    response += '\r\n'
                    response += response_body
                    client_connection.sendall(response.encode('utf-8'))
                    logging.info("Відправлено відповідь клієнту та закінчення обробки POST-запиту")
                except Exception as e:
                    logging.error(f"Помилка при обробці POST-запиту: {e}")
                    # Відправка відповіді з помилкою
                    response_body = '''
                    <!DOCTYPE html>
                    <html lang="uk">
                    <head>
                        <meta charset="UTF-8">
                        <title>Помилка сервера</title>
                    </head>
                    <body>
                        <h1>Сталася помилка на сервері</h1>
                        <p>Будь ласка, спробуйте пізніше.</p>
                    </body>
                    </html>
                    '''
                    response = 'HTTP/1.1 500 Internal Server Error\r\n'
                    response += 'Content-Type: text/html; charset=utf-8\r\n'
                    response += f'Content-Length: {len(response_body.encode("utf-8"))}\r\n'
                    response += 'Connection: close\r\n'
                    response += '\r\n'
                    response += response_body
                    client_connection.sendall(response.encode('utf-8'))
                    logging.info("Відправлено відповідь з помилкою та закінчення обробки POST-запиту")
            else:
                serve_404(client_connection)
        else:
            serve_404(client_connection)
    except Exception as e:
        logging.error(f"Помилка в handle_http: {e}")
    finally:
        client_connection.close()

# Функція HTTP-сервера
def http_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((HOST, HTTP_PORT))
    server_socket.listen(5)
    logging.info(f'HTTP сервер запущено на порту {HTTP_PORT}')

    while True:
        client_connection, client_address = server_socket.accept()
        threading.Thread(target=handle_http, args=(client_connection,)).start()

# Функція для відправки даних Socket-серверу
def send_to_socket_server(data):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)  # Таймаут 5 секунд
        try:
            sock.connect(('127.0.0.1', SOCKET_PORT))
            json_data = json.dumps(data)
            logging.info(f"Відправка даних Socket-серверу: {json_data}")
            sock.sendall(json_data.encode('utf-8'))
            # Отримання відповіді від Socket-сервера
            try:
                response = sock.recv(1024).decode('utf-8')
                logging.info(f"Отримано відповідь від Socket-сервера: {response}")
                return response
            except socket.timeout:
                logging.error("Таймаут при отриманні відповіді від Socket-сервера")
                return 'ERROR'
        except Exception as e:
            logging.error(f"Помилка зв'язку з Socket-сервером: {e}")
            return 'ERROR'

# Функція Socket-сервера
def socket_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((HOST, SOCKET_PORT))
    server_socket.listen(5)
    logging.info(f'Socket сервер запущено на порту {SOCKET_PORT}')

    while True:
        conn, addr = server_socket.accept()
        data = conn.recv(1024).decode('utf-8')
        if data:
            try:
                logging.info(f"Отримано дані від клієнта: {data}")
                message_data = json.loads(data)
                message_data['date'] = str(datetime.now())
            except Exception as e:
                logging.error(f"Помилка обробки даних: {e}")
                conn.sendall('ERROR'.encode('utf-8'))
                conn.close()
                continue

            try:
                # Підключення до MongoDB
                client = MongoClient('mongodb://mongodb:27017/', serverSelectionTimeoutMS=5000)
                client.server_info()  # Тестове підключення
                logging.info("Успішне підключення до бази даних MongoDB")
                db = client['messages_db']
                collection = db['messages']

                collection.insert_one(message_data)
                logging.info(f"Отримано та збережено повідомлення: {message_data}")

                # Відправка відповіді про успіх
                conn.sendall('SUCCESS'.encode('utf-8'))
            except Exception as e:
                logging.error(f"Помилка збереження даних: {e}")
                conn.sendall('ERROR'.encode('utf-8'))
        conn.close()

# Функція для відправки файлу клієнту
def serve_file(client_connection, file_path, mime_type):
    try:
        # Визначаємо, чи є контент текстовим
        is_text = mime_type.startswith('text/')

        if is_text:
            # Читаємо файл у текстовому режимі з кодуванням UTF-8
            with open(file_path, 'r', encoding='utf-8') as f:
                response_content = f.read()
            response_body = response_content.encode('utf-8')
        else:
            # Читаємо файл у бінарному режимі
            with open(file_path, 'rb') as f:
                response_body = f.read()

        # Формуємо HTTP-відповідь
        response = 'HTTP/1.1 200 OK\r\n'
        if is_text:
            response += f'Content-Type: {mime_type}; charset=utf-8\r\n'
        else:
            response += f'Content-Type: {mime_type}\r\n'
        response += f'Content-Length: {len(response_body)}\r\n'
        response += 'Connection: close\r\n'
        response += '\r\n'

        # Відправляємо відповідь клієнту
        client_connection.sendall(response.encode('utf-8') + response_body)
        logging.info(f"Відправлено файл {file_path}")
    except Exception as e:
        logging.error(f"Помилка в serve_file: {e}")
        serve_404(client_connection)

# Функція для відправки 404 сторінки
def serve_404(client_connection):
    try:
        with open('templates/error.html', 'r', encoding='utf-8') as f:
            response_content = f.read()
        response_body = response_content.encode('utf-8')
    except Exception as e:
        logging.error(f"Помилка при завантаженні сторінки 404: {e}")
        response_body = b'<h1>404 Not Found</h1>'
    response = 'HTTP/1.1 404 Not Found\r\n'
    response += 'Content-Type: text/html; charset=utf-8\r\n'
    response += f'Content-Length: {len(response_body)}\r\n'
    response += 'Connection: close\r\n'
    response += '\r\n'
    client_connection.sendall(response.encode('utf-8') + response_body)
    logging.info("Відправлено 404 сторінку")

# Функція для визначення MIME-типу файлу
def get_mime_type(file_path):
    if file_path.endswith('.css'):
        return 'text/css'
    elif file_path.endswith('.png'):
        return 'image/png'
    elif file_path.endswith('.html'):
        return 'text/html'
    elif file_path.endswith('.js'):
        return 'application/javascript'
    elif file_path.endswith('.ico'):
        return 'image/x-icon'
    else:
        return 'application/octet-stream'

if __name__ == '__main__':
    # Запуск серверів у різних процесах
    p1 = multiprocessing.Process(target=http_server)
    p2 = multiprocessing.Process(target=socket_server)
    p1.start()
    p2.start()
    logging.info("Запущено обидва сервери")
    p1.join()
    p2.join()
