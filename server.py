#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Serveur de réception des données système
Stockage dans MongoDB
"""

import socket
import json
import threading
import logging
import signal
import sys
import os
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from flask import Flask, request, jsonify

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='system_monitor_server.log'
)

# Configuration du serveur
SERVER_HOST = '0.0.0.0'  # Écoute sur toutes les interfaces
SERVER_PORT = 12345      # Port d'écoute (même que celui du client)
HTTP_PORT = 8080         # Port pour le serveur HTTP alternatif

# Configuration MongoDB
MONGO_HOST = 'localhost'
MONGO_PORT = 27017
MONGO_DB = 'system_monitoring'
MONGO_INITIAL_COLLECTION = 'system_initial_data'
MONGO_VARIABLE_COLLECTION = 'system_variable_data'

# Variables globales
server_running = True
connected_clients = {}
flask_app = Flask(__name__)

# Connexion à MongoDB
def connect_to_mongodb() -> Optional[MongoClient]:
    """Établit une connexion à la base de données MongoDB."""
    try:
        client = MongoClient(MONGO_HOST, MONGO_PORT)
        # Vérifier la connexion
        client.admin.command('ping')
        logging.info("Connexion à MongoDB établie avec succès")
        return client
    except PyMongoError as e:
        logging.error(f"Erreur lors de la connexion à MongoDB: {e}")
        return None

# Fonction pour sauvegarder les données dans MongoDB
def save_to_mongodb(data: Dict[str, Any]) -> bool:
    """Sauvegarde les données dans MongoDB."""
    try:
        mongo_client = connect_to_mongodb()
        if not mongo_client:
            return False
        
        db = mongo_client[MONGO_DB]
        
        # Déterminer s'il s'agit de données initiales ou variables
        # On considère que les données sont initiales si elles contiennent
        # des champs spécifiques aux données initiales comme 'os', 'type_machine', etc.
        is_initial_data = 'os' in data and 'type_machine' in data
        
        if is_initial_data:
            # Ajouter un champ d'horodatage si non présent
            if 'timestamp' not in data:
                data['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Ajouter ou mettre à jour les données initiales pour cette machine
            collection = db[MONGO_INITIAL_COLLECTION]
            
            # Utiliser l'ID de machine comme identifiant unique
            machine_id = data.get('machine_id', None)
            if not machine_id and 'adresse_mac' in data:
                machine_id = data['adresse_mac'].replace(':', '')
            
            if machine_id:
                # Mettre à jour si existe, sinon insérer
                result = collection.update_one(
                    {'machine_id': machine_id},
                    {'$set': data},
                    upsert=True
                )
                logging.info(f"Données initiales pour la machine {machine_id} enregistrées dans MongoDB")
            else:
                # Si pas d'identifiant, simplement insérer
                result = collection.insert_one(data)
                logging.info(f"Données initiales enregistrées dans MongoDB avec ID {result.inserted_id}")
        else:
            # Pour les données variables, on insère à chaque fois
            collection = db[MONGO_VARIABLE_COLLECTION]
            
            # Ajouter un champ d'horodatage si non présent
            if 'timestamp' not in data:
                data['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Utiliser l'ID de machine comme référence
            if 'machine_id' not in data:
                machine_id = data.get('machine_id', None)
                if not machine_id:
                    # Essayer de récupérer d'autres identificateurs
                    if 'adresse_mac' in data:
                        machine_id = data['adresse_mac'].replace(':', '')
                    data['machine_id'] = machine_id
            
            # Insérer les données variables
            result = collection.insert_one(data)
            logging.info(f"Données variables enregistrées dans MongoDB avec ID {result.inserted_id}")
        
        mongo_client.close()
        return True
    except PyMongoError as e:
        logging.error(f"Erreur lors de l'enregistrement dans MongoDB: {e}")
        return False
    except Exception as e:
        logging.error(f"Erreur inattendue lors de l'enregistrement dans MongoDB: {e}")
        return False

# Fonction pour extraire les données du message reçu
def extract_data_from_message(message: str) -> Optional[Dict[str, Any]]:
    """Extrait les données JSON du message reçu."""
    try:
        data = json.loads(message)
        
        # Si le message contient un fichier et son contenu
        if 'filename' in data and 'content' in data:
            try:
                # Extraire le contenu du fichier
                file_content = json.loads(data['content'])
                
                # Ajouter l'ID de la machine si disponible
                if 'machine_id' in data:
                    file_content['machine_id'] = data['machine_id']
                
                return file_content
            except json.JSONDecodeError:
                logging.error("Erreur lors du décodage du contenu du fichier")
                return None
        
        # Si le message est déjà un objet de données
        return data
    except json.JSONDecodeError:
        logging.error("Format de message invalide")
        return None
    except Exception as e:
        logging.error(f"Erreur lors de l'extraction des données: {e}")
        return None

# Gestion de la connexion client
def handle_client(client_socket: socket.socket, address: tuple) -> None:
    """Gère la connexion avec un client."""
    client_addr = f"{address[0]}:{address[1]}"
    logging.info(f"Nouvelle connexion acceptée de {client_addr}")
    
    connected_clients[client_addr] = {
        'socket': client_socket,
        'address': address,
        'connected_time': datetime.now()
    }
    
    buffer = ""
    
    try:
        while server_running:
            # Recevoir des données du client
            data = client_socket.recv(4096).decode('utf-8')
            if not data:
                logging.info(f"Client {client_addr} déconnecté")
                break
            
            # Ajouter les données au buffer
            buffer += data
            
            # Traiter les messages complets (terminés par \n)
            while '\n' in buffer:
                # Extraire un message complet
                message, buffer = buffer.split('\n', 1)
                
                # Traiter le message
                file_data = extract_data_from_message(message)
                
                if file_data:
                    # Sauvegarder dans MongoDB
                    if save_to_mongodb(file_data):
                        # Envoyer confirmation au client
                        client_socket.sendall("OK\n".encode('utf-8'))
                    else:
                        client_socket.sendall("ERROR: Échec de l'enregistrement dans MongoDB\n".encode('utf-8'))
                else:
                    client_socket.sendall("ERROR: Format de données invalide\n".encode('utf-8'))
    except socket.error as e:
        logging.warning(f"Erreur socket avec client {client_addr}: {e}")
    except Exception as e:
        logging.error(f"Erreur lors du traitement des données du client {client_addr}: {e}")
    finally:
        # Fermer la connexion et nettoyer
        client_socket.close()
        if client_addr in connected_clients:
            del connected_clients[client_addr]
        logging.info(f"Connexion fermée avec {client_addr}")

# Démarrage du serveur socket
def start_socket_server() -> None:
    """Démarre le serveur socket TCP."""
    try:
        # Créer un socket serveur
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Lier le socket à l'adresse et au port
        server_socket.bind((SERVER_HOST, SERVER_PORT))
        
        # Écouter les connexions entrantes
        server_socket.listen(5)
        logging.info(f"Serveur démarré et à l'écoute sur {SERVER_HOST}:{SERVER_PORT}")
        
        # Rendre le socket non bloquant pour pouvoir vérifier server_running
        server_socket.settimeout(1.0)
        
        # Boucle principale du serveur
        while server_running:
            try:
                # Accepter une connexion entrante
                client_socket, address = server_socket.accept()
                
                # Créer un thread pour gérer cette connexion
                client_thread = threading.Thread(target=handle_client, args=(client_socket, address))
                client_thread.daemon = True
                client_thread.start()
            except socket.timeout:
                # Timeout, vérifier si le serveur doit continuer à tourner
                continue
            except Exception as e:
                logging.error(f"Erreur lors de l'acceptation d'une connexion: {e}")
        
        # Fermer le socket serveur à la fin
        server_socket.close()
        logging.info("Serveur socket arrêté")
    except Exception as e:
        logging.error(f"Erreur lors du démarrage du serveur socket: {e}")

# Routes Flask pour le serveur HTTP alternatif
@flask_app.route('/submit', methods=['POST'])
def submit_data():
    """Point d'entrée HTTP pour soumettre des données."""
    try:
        # Vérifier si les données sont au format JSON
        if not request.is_json:
            return jsonify({"status": "error", "message": "Content-Type doit être application/json"}), 400
        
        # Récupérer les données
        data = request.get_json()
        
        # Sauvegarder dans MongoDB
        if save_to_mongodb(data):
            return jsonify({"status": "success", "message": "Données enregistrées avec succès"}), 200
        else:
            return jsonify({"status": "error", "message": "Échec de l'enregistrement des données"}), 500
    except Exception as e:
        logging.error(f"Erreur lors du traitement de la requête HTTP: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# Démarrage du serveur HTTP Flask
def start_http_server() -> None:
    """Démarre le serveur HTTP Flask."""
    try:
        flask_app.run(host=SERVER_HOST, port=HTTP_PORT, debug=False, use_reloader=False)
    except Exception as e:
        logging.error(f"Erreur lors du démarrage du serveur HTTP: {e}")

# Gestion de l'arrêt propre du serveur
def handle_exit(signum, frame) -> None:
    """Gère l'arrêt propre du serveur."""
    global server_running
    logging.info("Signal d'arrêt reçu, arrêt du serveur...")
    server_running = False
    
    # Fermer toutes les connexions client
    for client_addr, client_info in connected_clients.items():
        try:
            client_info['socket'].close()
            logging.info(f"Connexion fermée avec {client_addr}")
        except Exception as e:
            logging.error(f"Erreur lors de la fermeture de la connexion avec {client_addr}: {e}")
    
    # Attendre un peu que tout se termine proprement
    time.sleep(1)
    sys.exit(0)

# Fonction pour afficher les statistiques du serveur
def print_server_stats() -> None:
    """Affiche les statistiques du serveur."""
    try:
        # Se connecter à MongoDB
        mongo_client = connect_to_mongodb()
        if not mongo_client:
            print("Impossible de se connecter à MongoDB pour obtenir les statistiques")
            return
        
        db = mongo_client[MONGO_DB]
        
        # Nombre de machines uniques
        unique_machines = db[MONGO_INITIAL_COLLECTION].distinct('machine_id')
        num_machines = len(unique_machines)
        
        # Nombre total d'enregistrements
        num_initial_records = db[MONGO_INITIAL_COLLECTION].count_documents({})
        num_variable_records = db[MONGO_VARIABLE_COLLECTION].count_documents({})
        
        # Afficher les statistiques
        print("\n=== Statistiques du serveur ===")
        print(f"Nombre de machines surveillées: {num_machines}")
        print(f"Nombre d'enregistrements initiaux: {num_initial_records}")
        print(f"Nombre d'enregistrements variables: {num_variable_records}")
        print(f"Nombre total d'enregistrements: {num_initial_records + num_variable_records}")
        print(f"Connexions client actives: {len(connected_clients)}")
        print("==============================\n")
        
        mongo_client.close()
    except Exception as e:
        print(f"Erreur lors de l'affichage des statistiques: {e}")

# Fonction pour vérifier la santé de MongoDB
def check_mongodb_health() -> bool:
    """Vérifie la santé de la connexion MongoDB."""
    try:
        client = connect_to_mongodb()
        if client:
            client.admin.command('ping')
            client.close()
            return True
        return False
    except Exception:
        return False

# Point d'entrée principal
if __name__ == "__main__":
    try:
        # Vérifier si MongoDB est disponible
        if not check_mongodb_health():
            logging.error("MongoDB n'est pas disponible. Veuillez démarrer MongoDB et réessayer.")
            print("Erreur: MongoDB n'est pas disponible. Veuillez démarrer MongoDB et réessayer.")
            sys.exit(1)
        
        # Enregistrer les gestionnaires de signaux pour un arrêt propre
        signal.signal(signal.SIGINT, handle_exit)
        signal.signal(signal.SIGTERM, handle_exit)
        
        # Créer les collections MongoDB si elles n'existent pas
        mongo_client = connect_to_mongodb()
        if mongo_client:
            db = mongo_client[MONGO_DB]
            if MONGO_INITIAL_COLLECTION not in db.list_collection_names():
                db.create_collection(MONGO_INITIAL_COLLECTION)
            if MONGO_VARIABLE_COLLECTION not in db.list_collection_names():
                db.create_collection(MONGO_VARIABLE_COLLECTION)
            mongo_client.close()
        
        # Démarrer le serveur socket dans un thread
        socket_thread = threading.Thread(target=start_socket_server)
        socket_thread.daemon = True
        socket_thread.start()
        
        # Démarrer le serveur HTTP dans un thread
        http_thread = threading.Thread(target=start_http_server)
        http_thread.daemon = True
        http_thread.start()
        
        # Message de démarrage
        print(f"Serveur de surveillance système démarré.")
        print(f"Écoute des connexions socket sur le port {SERVER_PORT}")
        print(f"Serveur HTTP alternatif sur le port {HTTP_PORT}")
        print("Appuyez sur Ctrl+C pour arrêter le serveur.")
        
        # Boucle principale
        while server_running:
            time.sleep(10)  # Attendre 10 secondes
            print_server_stats()  # Afficher les statistiques
        
    except KeyboardInterrupt:
        logging.info("Serveur arrêté par l'utilisateur")
        print("\nArrêt du serveur...")
        server_running = False
    except Exception as e:
        logging.error(f"Erreur non gérée: {e}")
        sys.exit(1)
