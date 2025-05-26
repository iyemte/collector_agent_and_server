#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent de surveillance système - Collecte de données
Écris par Delibes
Fonctionne sur Kali Linux et Windows
"""

import socket
import json
import platform
import os
import time
import uuid
import psutil
from datetime import datetime, timedelta
import subprocess
import requests
import threading
import sys
import shutil
import logging
import glob
from typing import Dict, Any, List, Optional, Tuple

try:
    import GPUtil
    GPU_UTIL_AVAILABLE = True
except ImportError:
    GPU_UTIL_AVAILABLE = False

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='system_monitor.log'
)

# Adresse IP et port du serveur
SERVER_HOST = '192.168.1.155'
SERVER_PORT = 12345

# Intervalle de collecte et d'envoi (en secondes)
COLLECTION_INTERVAL = 2  # Collecte chaque 2 secondes
SEND_INTERVAL = 30  # Envoi toutes les 30 secondes

# Répertoire de stockage des données
DATA_DIR = "data"

# Vérifier si le répertoire existe, sinon le créer
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# Variable globale pour le compteur de fichiers et vérifier si les données initiales ont été collectées
file_counter = 1
initial_data_saved = False

# Identifiant unique de la machine (utilisé pour le nom du fichier JSON)
MACHINE_ID = str(uuid.getnode())

# Seuil d'utilisation des ressources (en pourcentage)
RESOURCE_THRESHOLD = 80  # 80% d'utilisation

# Temps de démarrage du système
system_boot_time = datetime.fromtimestamp(psutil.boot_time())

# Heure de démarrage du script
script_start_time = datetime.now()

# Dernière heure d'arrêt (si disponible)
last_shutdown_time = None


def get_next_filename() -> str:
    """Trouve le prochain nom de fichier disponible."""
    global file_counter
    
    while True:
        filename = f"{DATA_DIR}/{file_counter}.json"
        if not os.path.exists(filename):
            return filename
        file_counter += 1
        
def reset_file_counter():
    """Réinitialise le compteur de fichiers en trouvant le dernier fichier existant."""
    global file_counter
    
    file_counter = 1
    while os.path.exists(f"{DATA_DIR}/{file_counter}.json"):
        file_counter += 1
    
    logging.info(f"Compteur de fichiers réinitialisé à {file_counter}")

# Exemple d'utilisation au démarrage du script
def initialize_file_system():
    """Initialise le système de fichiers."""
    # Créer le répertoire de données s'il n'existe pas
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    
    # Optionnel: réinitialiser le compteur basé sur les fichiers existants
    reset_file_counter()
    
    logging.info(f"Système de fichiers initialisé. Prochain fichier: {file_counter}.json")
    
            
# Fonction pour obtenir des informations sur les utilisateurs connectés
def get_logged_users() -> List[Dict[str, str]]:
    """Récupère la liste des utilisateurs connectés au système."""
    users = []
    for user in psutil.users():
        users.append({
            "username": user.name,
            "terminal": user.terminal,
            "host": user.host,
            "started": datetime.fromtimestamp(user.started).strftime("%Y-%m-%d %H:%M:%S"),
            "pid": user.pid if hasattr(user, 'pid') else None
        })
    return users

# Fonction pour obtenir la résolution d'écran
def get_screen_resolution() -> Optional[str]:
    """Récupère la résolution d'écran du système."""
    resolution = None
    try:
        if platform.system() == "Windows":
            import ctypes
            user32 = ctypes.windll.user32
            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)
            resolution = f"{width}x{height}"
        elif platform.system() == "Linux":
            # Tenter d'utiliser xrandr sur Linux
            cmd = "xrandr | grep ' connected' | head -n 1 | awk '{print $3}' | cut -d'+' -f1"
            try:
                resolution = subprocess.check_output(cmd, shell=True).decode().strip()
            except subprocess.SubprocessError:
                resolution = "Non disponible"
    except Exception as e:
        logging.error(f"Erreur lors de la récupération de la résolution d'écran: {e}")
        resolution = "Non disponible"
    return resolution

# Fonction pour déterminer le type de machine
def get_machine_type() -> int:
    """Détermine si la machine est un portable (0) ou un desktop (1)."""
    system = platform.system()
    if system == "Windows":
        try:
            # Vérifier si c'est un portable sur Windows
            import ctypes
            power_status = ctypes.c_int()
            ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power_status))
            if power_status.value & 0x8:  # Un bit spécifique indique une batterie
                return 0  # Laptop
            return 1  # Desktop
        except Exception:
            # Méthode alternative: vérifier la présence d'une batterie
            if hasattr(psutil, "sensors_battery") and psutil.sensors_battery():
                return 0  # Laptop
            return 1  # Desktop
    elif system == "Linux":
        # Vérifier si c'est un portable sur Linux
        if os.path.exists("/sys/class/power_supply/BAT0") or os.path.exists("/sys/class/power_supply/BAT1"):
            return 0  # Laptop
        if "Macbook" in platform.node() or "MacBook" in platform.node():
            return 0  # Laptop
        return 1  # Desktop
    elif system == "Darwin":
        model = subprocess.getoutput("sysctl -n hw.model")
        if "MacBook" in model:
            return 0  # Laptop
        elif "iMac" in model:
            return 1  # Desktop
        else:
            return 1  # Desktop par défaut
    else:
        return 1  # Desktop par défaut

# Fonction pour obtenir les informations sur le BIOS et la carte mère
def get_bios_motherboard_info() -> Dict[str, str]:
    """Récupère les informations sur le BIOS et la carte mère."""
    bios_info = {"BIOS": "Non disponible", "Carte mère": "Non disponible"}
    
    if platform.system() == "Windows":
        try:
            # Utiliser WMI pour obtenir des informations sur le BIOS
            import wmi
            c = wmi.WMI()
            for bios in c.Win32_BIOS():
                bios_info["BIOS"] = {
                    "Fabricant": bios.Manufacturer,
                    "Version": bios.Version,
                    "Date": bios.ReleaseDate
                }
            
            for board in c.Win32_BaseBoard():
                bios_info["Carte mère"] = {
                    "Fabricant": board.Manufacturer,
                    "Modèle": board.Product,
                    "SerialNumber": board.SerialNumber
                }
        except Exception as e:
            logging.error(f"Erreur lors de la récupération des informations BIOS/Carte mère sur Windows: {e}")
    
    elif platform.system() == "Linux":
        try:
            # Essayer d'abord sans sudo
            try:
                # Utiliser dmidecode pour obtenir des informations sur le BIOS
                bios_output = subprocess.check_output("dmidecode -t bios", shell=True).decode()
                vendor = next((line.split("Vendor:")[1].strip() for line in bios_output.splitlines() if "Vendor:" in line), "Non disponible")
                version = next((line.split("Version:")[1].strip() for line in bios_output.splitlines() if "Version:" in line), "Non disponible")
                release_date = next((line.split("Release Date:")[1].strip() for line in bios_output.splitlines() if "Release Date:" in line), "Non disponible")
                bios_info["BIOS"] = {"Fabricant": vendor, "Version": version, "Date de sortie": release_date}
                
                # Utiliser dmidecode pour obtenir des informations sur la carte mère
                board_output = subprocess.check_output("dmidecode -t baseboard", shell=True).decode()
                manufacturer = next((line.split("Manufacturer:")[1].strip() for line in board_output.splitlines() if "Manufacturer:" in line), "Non disponible")
                product = next((line.split("Product Name:")[1].strip() for line in board_output.splitlines() if "Product Name:" in line), "Non disponible")
                bios_info["Carte mère"] = {"Fabricant": manufacturer, "Modèle": product}
            except (subprocess.CalledProcessError, PermissionError) as e:
                # Si l'exécution sans sudo échoue, utiliser des méthodes alternatives
                logging.warning(f"Impossible d'exécuter dmidecode sans privilèges: {e}")
                
                # Méthode alternative pour obtenir des informations sur le système
                # Utiliser /sys/class/dmi/id/ qui est souvent accessible sans privilèges
                try:
                    if os.path.exists('/sys/class/dmi/id/bios_vendor'):
                        with open('/sys/class/dmi/id/bios_vendor', 'r') as f:
                            vendor = f.read().strip()
                    if os.path.exists('/sys/class/dmi/id/bios_version'):
                        with open('/sys/class/dmi/id/bios_version', 'r') as f:
                            version = f.read().strip()
                    if os.path.exists('/sys/class/dmi/id/bios_date'):
                        with open('/sys/class/dmi/id/bios_date', 'r') as f:
                            release_date = f.read().strip()
                    
                    bios_info["BIOS"] = {"Fabricant": vendor if 'vendor' in locals() else "Non disponible", 
                                      "Version": version if 'version' in locals() else "Non disponible", 
                                      "Date de sortie": release_date if 'release_date' in locals() else "Non disponible"}
                    
                    # Informations sur la carte mère
                    if os.path.exists('/sys/class/dmi/id/board_vendor'):
                        with open('/sys/class/dmi/id/board_vendor', 'r') as f:
                            manufacturer = f.read().strip()
                    if os.path.exists('/sys/class/dmi/id/board_name'):
                        with open('/sys/class/dmi/id/board_name', 'r') as f:
                            product = f.read().strip()
                    
                    bios_info["Carte mère"] = {"Fabricant": manufacturer if 'manufacturer' in locals() else "Non disponible", 
                                           "Modèle": product if 'product' in locals() else "Non disponible"}
                except Exception as e2:
                    logging.warning(f"Méthode alternative pour obtenir les informations BIOS/Carte mère a échoué: {e2}")
                    # Laisser les valeurs par défaut
            except:
                pass
        except Exception as e:
            logging.error(f"Erreur lors de la récupération des informations BIOS/Carte mère sur Linux: {e}")
    
    return bios_info

# Fonction pour obtenir les informations sur les périphériques USB
def get_usb_devices() -> List[Dict[str, str]]:
    """Récupère les informations sur les périphériques USB connectés."""
    usb_devices = []
    
    if platform.system() == "Windows":
        try:
            import wmi
            c = wmi.WMI()
            for device in c.Win32_USBControllerDevice():
                try:
                    dependent = device.Dependent
                    if dependent:
                        dev_info = {}
                        if hasattr(dependent, 'DeviceID'):
                            dev_info["ID"] = dependent.DeviceID
                        if hasattr(dependent, 'Description'):
                            dev_info["Description"] = dependent.Description
                        if dev_info:
                            usb_devices.append(dev_info)
                except:
                    pass
        except Exception as e:
            logging.error(f"Erreur lors de la récupération des périphériques USB sur Windows: {e}")
    
    elif platform.system() == "Linux":
        try:
            usb_output = subprocess.check_output("lsusb", shell=True).decode()
            for line in usb_output.strip().split('\n'):
                if line:
                    usb_devices.append({"Description": line})
        except Exception as e:
            logging.error(f"Erreur lors de la récupération des périphériques USB sur Linux: {e}")
    
    return usb_devices

# Fonction pour obtenir les informations sur le GPU NVIDIA
def get_gpu_info() -> Dict[str, Any]:
    """Récupère les informations sur le GPU (NVIDIA)."""
    gpu_info = {"Disponible": False}
    
    try:
        if platform.system() == "Windows":
            try:
                import wmi
                nvidia_query = "SELECT * FROM Win32_VideoController WHERE Name LIKE '%NVIDIA%'"
                c = wmi.WMI()
                for gpu in c.query(nvidia_query):
                    gpu_info = {
                        "Disponible": True,
                        "Nom": gpu.Name,
                        "RAM": f"{int(int(gpu.AdapterRAM) / (1024**2))} MB" if hasattr(gpu, 'AdapterRAM') else "Non disponible",
                        "DriverVersion": gpu.DriverVersion if hasattr(gpu, 'DriverVersion') else "Non disponible"
                    }
                    break
            except Exception as e:
                logging.error(f"Erreur lors de la récupération des infos GPU via WMI: {e}")
        
        # Essayer nvidia-smi sur les deux plateformes
        try:
            nvidia_output = subprocess.check_output("nvidia-smi --query-gpu=name,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader", shell=True).decode().strip()
            if nvidia_output:
                parts = nvidia_output.split(', ')
                if len(parts) >= 4:
                    gpu_info = {
                        "Disponible": True,
                        "Nom": parts[0],
                        "RAM": parts[1],
                        "Utilisation": parts[2],
                        "Température": parts[3]
                    }
        except Exception:
            pass
            
        # Utiliser GPUtil si disponible
        try:
            import GPUtil
            gpus = GPUtil.getGPUs()
            if gpus:
                gpu = gpus[0]  # Premier GPU
                gpu_info = {
                    "Disponible": True,
                    "Nom": gpu.name,
                    "RAM": f"{gpu.memoryTotal} MB",
                    "Utilisation": f"{gpu.load * 100:.1f}%",
                    "Température": f"{gpu.temperature}°C",
                    "Mémoire_utilisée": f"{gpu.memoryUsed} MB"
                }
        except ImportError:
            logging.info("GPUtil n'est pas installé, utilisation des méthodes alternatives")
        except Exception as e:
            logging.error(f"Erreur avec GPUtil: {e}")
            
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des informations GPU: {e}")
    
    return gpu_info
    
    
# Fonction pour obtenir les informations sur les interfaces réseau
def get_network_interfaces() -> List[Dict[str, Any]]:
    """Récupère les informations sur les interfaces réseau."""
    network_interfaces = []
    
    try:
        for interface_name, interface_addresses in psutil.net_if_addrs().items():
            interface_info = {"nom": interface_name, "adresses": []}
            
            for addr in interface_addresses:
                address_info = {}
                if addr.family == socket.AF_INET:  # IPv4
                    address_info["type"] = "IPv4"
                    address_info["adresse"] = addr.address
                    address_info["netmask"] = addr.netmask
                    address_info["broadcast"] = addr.broadcast
                elif addr.family == socket.AF_INET6:  # IPv6
                    address_info["type"] = "IPv6"
                    address_info["adresse"] = addr.address
                    address_info["netmask"] = addr.netmask
                    address_info["broadcast"] = addr.broadcast
                elif addr.family == psutil.AF_LINK:  # MAC address
                    address_info["type"] = "MAC"
                    address_info["adresse"] = addr.address
                
                if address_info:
                    interface_info["adresses"].append(address_info)
            
            # Ajouter des statistiques si disponibles
            if interface_name in psutil.net_if_stats():
                stats = psutil.net_if_stats()[interface_name]
                interface_info["statut"] = "Up" if stats.isup else "Down"
                interface_info["vitesse"] = f"{stats.speed} Mbps" if stats.speed > 0 else "Inconnue"
                interface_info["duplex"] = stats.duplex
                interface_info["mtu"] = stats.mtu
            
            network_interfaces.append(interface_info)
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des interfaces réseau: {e}")
    
    return network_interfaces

# Fonction pour vérifier la connexion Internet
def is_internet_connected() -> bool:
    """Vérifie si l'ordinateur est connecté à Internet."""
    try:
        # Tentative de connexion à Google DNS
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        pass
    return False

# Fonction pour obtenir les informations sur les partitions de disque
def get_disk_partitions() -> List[Dict[str, Any]]:
    """Récupère les informations sur les partitions de disque."""
    partitions = []
    
    try:
        for part in psutil.disk_partitions(all=True):
            partition_info = {
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "opts": part.opts
            }
            
            try:
                usage = psutil.disk_usage(part.mountpoint)
                partition_info.update({
                    "total": bytes_to_human_readable(usage.total),
                    "used": bytes_to_human_readable(usage.used),
                    "free": bytes_to_human_readable(usage.free),
                    "percent_used": usage.percent,
                    "percent_free": 100 - usage.percent
                })
            except (PermissionError, FileNotFoundError):
                # Certaines partitions peuvent ne pas être accessibles
                partition_info.update({
                    "total": "Non disponible",
                    "used": "Non disponible",
                    "free": "Non disponible",
                    "percent_used": "Non disponible",
                    "percent_free": "Non disponible"
                })
            
            partitions.append(partition_info)
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des partitions de disque: {e}")
    
    return partitions

# Fonction pour convertir des octets en format lisible
def bytes_to_human_readable(bytes_value: int) -> str:
    """Convertit un nombre d'octets en format lisible par un humain."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if bytes_value < 1024.0 or unit == 'PB':
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0

# Fonction pour obtenir la température du CPU
def get_cpu_temperature() -> Optional[float]:
    """Récupère la température du CPU si disponible."""
    temperature = None
    
    try:
        if platform.system() == "Linux":
            try:
                # Essayer avec sensors
                output = subprocess.check_output(["sensors"], universal_newlines=True)
                for line in output.split("\n"):
                    if "Core" in line and "°C" in line:
                        temperature = float(line.split("+")[1].split("°C")[0].strip())
                        break
            except (subprocess.SubprocessError, FileNotFoundError):
                try:
                    # Essayer avec la lecture directe des fichiers système
                    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                        temperature = float(f.read().strip()) / 1000.0
                except (FileNotFoundError, IOError, ValueError):
                    pass
        
        elif platform.system() == "Windows":
            try:
                import wmi
                w = wmi.WMI(namespace="root\\wmi")
                temperature_info = w.MSAcpi_ThermalZoneTemperature()[0]
                # Convertir la température de Kelvin en Celsius
                temperature = (temperature_info.CurrentTemperature / 10.0) - 273.15
            except Exception:
                pass
    except Exception as e:
        logging.error(f"Erreur lors de la récupération de la température CPU: {e}")
    
    return temperature

# Fonction pour obtenir le pourcentage de batterie
def get_battery_info() -> Dict[str, Any]:
    """Récupère les informations complètes de batterie."""
    battery_info = {
        "has_battery": 1,  # 1 = pas de batterie, True = batterie présente
        "percent": "Non disponible",
        "capacity": "Non disponible",
        "autonomy": "Non disponible",
        "power_plugged": "Non disponible"
    }
    
    try:
        battery = psutil.sensors_battery()
        if battery:
            battery_info["has_battery"] = 0  # Batterie présente
            battery_info["percent"] = battery.percent
            battery_info["power_plugged"] = battery.power_plugged
            
            # Calculer l'autonomie
            if battery.secsleft != psutil.POWER_TIME_UNLIMITED and battery.secsleft > 0:
                hours = battery.secsleft // 3600
                minutes = (battery.secsleft % 3600) // 60
                battery_info["autonomy"] = f"{hours}h {minutes}min"
            elif battery.power_plugged:
                battery_info["autonomy"] = "Branché secteur"
            else:
                battery_info["autonomy"] = "Calcul en cours"
            
            # Essayer d'obtenir la capacité de la batterie
            try:
                if platform.system() == "Linux":
                    capacity_paths = [
                        "/sys/class/power_supply/BAT0/energy_full_design",
                        "/sys/class/power_supply/BAT1/energy_full_design",
                        "/sys/class/power_supply/BAT0/charge_full_design",
                        "/sys/class/power_supply/BAT1/charge_full_design"
                    ]
                    for path in capacity_paths:
                        if os.path.exists(path):
                            with open(path, 'r') as f:
                                capacity_value = int(f.read().strip())
                                if "energy" in path:
                                    battery_info["capacity"] = f"{capacity_value / 1000000:.1f} Wh"
                                else:
                                    battery_info["capacity"] = f"{capacity_value / 1000:.0f} mAh"
                                break
                elif platform.system() == "Windows":
                    try:
                        import wmi
                        c = wmi.WMI()
                        for bat in c.Win32_Battery():
                            if hasattr(bat, 'DesignCapacity') and bat.DesignCapacity:
                                battery_info["capacity"] = f"{bat.DesignCapacity} mWh"
                                break
                    except Exception:
                        pass
            except Exception as e:
                logging.error(f"Erreur lors de la récupération de la capacité de batterie: {e}")
        else:
            battery_info["has_battery"] = 1  # Pas de batterie
            logging.info("Aucune batterie détectée sur ce système")
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des informations de batterie: {e}")
        battery_info["has_battery"] = 1  # En cas d'erreur
    
    logging.info(f"Battery data collected: {battery_info}")
    return battery_info

# Fonction pour vérifier si le seuil d'utilisation des ressources est atteint
def check_resource_threshold() -> Dict[str, bool]:
    """Vérifie si le seuil d'utilisation des ressources est atteint."""
    threshold_reached = {
        "cpu": False,
        "memory": False,
        "disk": False,
        "timestamp": None
    }
    
    try:
        # Vérifier l'utilisation du CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)
        if cpu_percent > RESOURCE_THRESHOLD:
            threshold_reached["cpu"] = True
        
        # Vérifier l'utilisation de la mémoire
        memory = psutil.virtual_memory()
        if memory.percent > RESOURCE_THRESHOLD:
            threshold_reached["memory"] = True
        
        # Vérifier l'utilisation du disque
        disk = psutil.disk_usage('/')
        if disk.percent > RESOURCE_THRESHOLD:
            threshold_reached["disk"] = True
        
        # Si un seuil est atteint, enregistrer l'horodatage
        if threshold_reached["cpu"] or threshold_reached["memory"] or threshold_reached["disk"]:
            threshold_reached["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        logging.error(f"Erreur lors de la vérification des seuils d'utilisation: {e}")
    
    return threshold_reached

# Fonction pour collecter les données initiales (une fois au démarrage)
def collect_initial_data() -> Dict[str, Any]:
    """Collecte les données initiales sur le système."""
    try:
        # Informations sur le système d'exploitation
        os_info = {
            "nom": platform.system(),
            "version": platform.version(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "hostname": platform.node()
        }
        
        # Informations sur le processeur
        cpu_info = {
            "type": platform.processor(),
            "architecture": platform.machine(),
            "bits": "64-bit" if platform.machine().endswith('64') else "32-bit",
            "coeurs_physiques": psutil.cpu_count(logical=False),
            "coeurs_logiques": psutil.cpu_count(logical=True),
            "frequence": {
                "actuelle": psutil.cpu_freq().current if psutil.cpu_freq() else "Non disponible",
                "min": psutil.cpu_freq().min if psutil.cpu_freq() and hasattr(psutil.cpu_freq(), 'min') else "Non disponible",
                "max": psutil.cpu_freq().max if psutil.cpu_freq() and hasattr(psutil.cpu_freq(), 'max') else "Non disponible"
            }
        }
        
        # Informations sur la mémoire
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        memory_info = {
            "ram": {
                "total": bytes_to_human_readable(memory.total),
                "disponible": bytes_to_human_readable(memory.available),
                "utilisee": bytes_to_human_readable(memory.used),
                "pourcentage_utilise": memory.percent,
                "pourcentage_libre": 100 - memory.percent
            },
            "swap": {
                "total": bytes_to_human_readable(swap.total),
                "disponible": bytes_to_human_readable(swap.free),
                "utilisee": bytes_to_human_readable(swap.used),
                "pourcentage_utilise": swap.percent,
                "pourcentage_libre": 100 - swap.percent
            },
            "cache": {
                "total": bytes_to_human_readable(memory.cached) if hasattr(memory, 'cached') else "Non disponible",
                "pourcentage": (memory.cached / memory.total * 100) if hasattr(memory, 'cached') and memory.total > 0 else "Non disponible"
            }
        }
        
        # Informations sur le disque
        disk = psutil.disk_usage('/')
        disk_info = {
            "total": bytes_to_human_readable(disk.total),
            "disponible": bytes_to_human_readable(disk.free),
            "utilise": bytes_to_human_readable(disk.used),
            "pourcentage_utilise": disk.percent,
            "pourcentage_libre": 100 - disk.percent
        }
        
        # Type de machine (0 pour laptop, 1 pour desktop)
        machine_type = get_machine_type()
        
        # Adresse MAC
        mac_address = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff) for elements in range(0,8*6,8)][::-1])
        
        # Résolution d'écran
        screen_resolution = get_screen_resolution()
        
        # Information GPU (NVIDIA)
        gpu_info = get_gpu_info()
        
        # Interfaces réseau
        network_interfaces = get_network_interfaces()
        
        # BIOS et carte mère
        bios_motherboard_info = get_bios_motherboard_info()
        
        # Utilisateurs connectés
        logged_users = get_logged_users()
        
        # Partitions de disque
        disk_partitions = get_disk_partitions()
        
        # Périphériques USB
        usb_devices = get_usb_devices()
        
         # CORRECTION: Récupérer les informations batterie ici
        battery_initial_info = get_battery_info()
        
        # Assembler toutes les données
        system_data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "os": os_info,
            "type_machine": machine_type,
            "cpu": cpu_info,
            "memoire": memory_info,
            "disque": disk_info,
            "adresse_mac": mac_address,
            "resolution_ecran": screen_resolution,
            "gpu": gpu_info,
            "interfaces_reseau": network_interfaces,
            "bios_carte_mere": bios_motherboard_info,
            "utilisateurs_connectes": logged_users,
            "partitions_disque": disk_partitions,
            "peripheriques_usb": usb_devices,
            "battery_initial": battery_initial_info,
            "heure_demarrage_systeme": system_boot_time.strftime("%Y-%m-%d %H:%M:%S"),
            "heure_demarrage_script": script_start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "heure_arret_precedent": last_shutdown_time.strftime("%Y-%m-%d %H:%M:%S") if last_shutdown_time else "Non disponible"
        }
        
        return system_data
    except Exception as e:
        logging.error(f"Erreur lors de la collecte des données initiales: {e}")
        return {"error": str(e)}



# Fonction pour collecter les données variables (toutes les X secondes)
def collect_variable_data() -> Dict[str, Any]:
    """Collecte les données variables du système."""
    try:
        # CPU par cœur
        cpu_per_core = psutil.cpu_percent(interval=0.1, percpu=True)
        cpu_cores_data = [{"core": i, "utilisation": percent, "libre": 100 - percent} for i, percent in enumerate(cpu_per_core)]
        
        # Utilisation mémoire
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        # Utilisation disque
        disk = psutil.disk_usage('/')
        
        # Température CPU
        cpu_temp = get_cpu_temperature()
        
        # Utilisation GPU
        # Utilisation GPU avec GPUtil
        gpu_usage = None
        if GPU_UTIL_AVAILABLE:
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu = gpus[0]
                    gpu_usage = {
                        "gpu": f"{gpu.load * 100:.1f}%",
                        "memory": f"{(gpu.memoryUsed / gpu.memoryTotal) * 100:.1f}%"
                    }
            except Exception as e:
                logging.error(f"Erreur GPU usage: {e}")
        
        # Bande passante réseau
        net_io_counters = psutil.net_io_counters()
        
        # Vérifier la connexion Internet
        internet_connected = is_internet_connected()
        
        # Nombre de processus actifs
        process_count = len(psutil.pids())
        
        # Pourcentage de batterie
        battery_info = get_battery_info()
        
        # Temps de fonctionnement (uptime)
        uptime_seconds = time.time() - psutil.boot_time()
        uptime_str = str(timedelta(seconds=uptime_seconds))
        
        # Vérifier si le seuil d'utilisation des ressources est atteint
        threshold_check = check_resource_threshold()
        
        # Assembler les données variables
        variable_data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cpu": {
                "global_utilise": sum(cpu_per_core) / len(cpu_per_core) if cpu_per_core else 0,
                "global_disponible": 100 - (sum(cpu_per_core) / len(cpu_per_core)) if cpu_per_core else 100,
                "par_coeur": cpu_cores_data,
                "temperature": cpu_temp
            },
            "memoire": {
                "ram": {
                    "pourcentage_utilise": memory.percent,
                    "pourcentage_libre": 100 - memory.percent,
                    "utilisee": bytes_to_human_readable(memory.used),
                    "disponible": bytes_to_human_readable(memory.available)
                },
                "swap": {
                    "pourcentage_utilise": swap.percent,
                    "pourcentage_libre": 100 - swap.percent,
                    "utilisee": bytes_to_human_readable(swap.used),
                    "disponible": bytes_to_human_readable(swap.free)
                },
                "cache": {
                    "utilisee": bytes_to_human_readable(memory.cached) if hasattr(memory, 'cached') else "Non disponible"
                }
            },
            "disque": {
                "pourcentage_utilise": disk.percent,
                "pourcentage_libre": 100 - disk.percent
            },
            "gpu_utilisation": gpu_usage,
            "reseau": {
                "octets_envoyes": bytes_to_human_readable(net_io_counters.bytes_sent),
                "octets_recus": bytes_to_human_readable(net_io_counters.bytes_recv),
                "paquets_envoyes": net_io_counters.packets_sent,
                "paquets_recus": net_io_counters.packets_recv,
                "erreurs_reception": net_io_counters.errin,
                "erreurs_envoi": net_io_counters.errout,
                "paquets_supprimes_reception": net_io_counters.dropin,
                "paquets_supprimes_envoi": net_io_counters.dropout
            },
            "connexion_internet": internet_connected,
            "nombre_processus": process_count,
            "battery": battery_info,
            "uptime": uptime_str,
            "seuil_atteint": threshold_check
        }
        return variable_data
    except Exception as e:
        logging.error(f"Erreur lors de la collecte des données variables: {e}")
        return {"error": str(e)}


def save_initial_data():
    """Sauvegarde les données initiales dans 1.json (une seule fois)."""
    global initial_data_saved
    
    if initial_data_saved or os.path.exists(f"{DATA_DIR}/1.json"):
        logging.info("Données initiales déjà sauvegardées, passage ignoré")
        return
    
    try:
        initial_data = collect_initial_data()
        
        # Forcer la sauvegarde dans 1.json
        filename = f"{DATA_DIR}/1.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(initial_data, f, ensure_ascii=False, indent=2)
        
        initial_data_saved = True
        logging.info(f"Données initiales sauvegardées dans {filename}")
        
    except Exception as e:
        logging.error(f"Erreur lors de la sauvegarde des données initiales: {e}")

def save_variable_data_to_file(data: Dict[str, Any]) -> str:
    global file_counter
    
    # Trouver le prochain numéro disponible
    while os.path.exists(f"{DATA_DIR}/{file_counter}.json"):
        file_counter += 1
    
    filename = f"{DATA_DIR}/{file_counter}.json"
    
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"Données variables sauvegardées dans {filename}")
        file_counter += 1  # Incrémenter pour le prochain fichier
        return filename
    except Exception as e:
        logging.error(f"Erreur lors de la sauvegarde des données variables: {e}")
        return None



def initialize_data_collection():
    """Initialise la collecte de données."""
    global initial_data_saved, file_counter
    
    # Créer le répertoire de données s'il n'existe pas
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    
    # Vérifier si 1.json existe déjà
    if os.path.exists(f"{DATA_DIR}/1.json"):
        initial_data_saved = True
        logging.info("Fichier de données initiales (1.json) déjà existant")
    else:
        initial_data_saved = False
    
    # Trouver le prochain numéro de fichier pour les données variables
    file_counter = 2  # Commencer à 2 pour les données variables
    while os.path.exists(f"{DATA_DIR}/{file_counter}.json"):
        file_counter += 1
    
    logging.info(f"Système initialisé. Prochain fichier de données variables: {file_counter}.json")


# Fonction pour envoyer les fichiers JSON au serveur
def send_files_to_server() -> None:
    """Envoie tous les fichiers JSON au serveur distant."""
    logging.info(f"Tentative d'envoi des fichiers au serveur {SERVER_HOST}:{SERVER_PORT}")

    # Liste tous les fichiers JSON dans le répertoire DATA_DIR
    json_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.json')]
    
    if not json_files:
        logging.info("Aucun fichier à envoyer.")
        return
    
    # Tenter de se connecter au serveur
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.settimeout(5)  # Timeout de 5 secondes
        client_socket.connect((SERVER_HOST, SERVER_PORT))
        logging.info(f"Connecté au serveur {SERVER_HOST}:{SERVER_PORT}")
        
        # Envoyer chaque fichier
        for json_file in json_files:
            file_path = os.path.join(DATA_DIR, json_file)
            try:
                # Lire le contenu du fichier
                with open(file_path, 'r', encoding='utf-8') as f:
                    file_data = f.read()
                
                # Préparer les données à envoyer
                data_to_send = {
                    "filename": json_file,
                    "content": file_data,
                    "machine_id": MACHINE_ID,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                
                # Convertir en JSON et envoyer
                data_json = json.dumps(data_to_send)
                client_socket.sendall(f"{data_json}\n".encode('utf-8'))
                
                # Attendre la confirmation du serveur
                response = client_socket.recv(1024).decode('utf-8').strip()
                
                if response == "OK":
                    logging.info(f"Fichier {json_file} envoyé avec succès, suppression du fichier local")
                    os.remove(file_path)
                    # Supprimer aussi le fichier marqueur s'il existe
                    sent_marker = file_path + ".sent"
                    if os.path.exists(sent_marker):
                        os.remove(sent_marker)
                else:
                    logging.warning(f"Problème lors de l'envoi du fichier {json_file}: {response}")
            except Exception as e:
                logging.error(f"Erreur lors de l'envoi du fichier {json_file}: {e}")
        
        # Fermer la connexion
        client_socket.close()
        logging.info("Connexion au serveur fermée")
        
    except (socket.timeout, ConnectionRefusedError) as e:
        logging.warning(f"Impossible de se connecter au serveur: {e}")
    except Exception as e:
        logging.error(f"Erreur lors de la connexion au serveur: {e}")
    
# Fonction alternative pour envoyer les données via HTTP (au cas où le serveur TCP ne fonctionne pas)
def send_data_via_http(data: Dict[str, Any]) -> bool:
    """Envoie les données via une requête HTTP POST."""
    try:
        url = f"http://{SERVER_HOST}:{SERVER_PORT}/submit"
        headers = {"Content-Type": "application/json"}
        
        response = requests.post(url, json=data, headers=headers, timeout=5)
        
        if response.status_code == 200:
            logging.info("Données envoyées avec succès via HTTP")
            return True
        else:
            logging.warning(f"Échec de l'envoi des données via HTTP: {response.status_code}")
            return False
    except Exception as e:
        logging.error(f"Erreur lors de l'envoi des données via HTTP: {e}")
        return False

def get_data_directory_size() -> int:
    """Calcule la taille totale des fichiers JSON dans le répertoire de données (en octets)"""
    total_size = 0
    try:
        for filename in os.listdir(DATA_DIR):
            if filename.endswith('.json'):
                file_path = os.path.join(DATA_DIR, filename)
                if os.path.isfile(file_path):
                    total_size += os.path.getsize(file_path)
    except Exception as e:
        logging.error(f"Erreur lors du calcul de la taille du répertoire: {e}")
    return total_size

def is_storage_limit_reached() -> bool:
    """Vérifie si la limite de stockage de 200Mo est atteinte"""
    current_size = get_data_directory_size()
    limit_bytes = 200 * 1024 * 1024  # 200 Mo en octets
    if current_size >= limit_bytes:
        logging.warning(f"Limite de stockage atteinte: {bytes_to_human_readable(current_size)} / 200 Mo")
        return True
    return False
 

# Fonction pour gérer l'arrêt propre du script
def handle_exit(signum, frame) -> None:
    """Gère l'arrêt propre du script."""
    logging.info("Signal d'arrêt reçu, arrêt du script...")
    # Tenter d'envoyer tous les fichiers restants avant de quitter
    send_files_to_server()
    sys.exit(0)

def cleanup_old_files(days_to_keep: int = 30) -> None:
    """Supprime les fichiers JSON et leurs marqueurs après X jours (optionnel)"""
    try:
        cutoff_time = time.time() - (days_to_keep * 24 * 3600)
        for filename in os.listdir(DATA_DIR):
            file_path = os.path.join(DATA_DIR, filename)
            if os.path.isfile(file_path) and os.path.getmtime(file_path) < cutoff_time:
                if filename.endswith('.json') or filename.endswith('.json.sent'):
                    os.remove(file_path)
                    logging.info(f"Ancien fichier supprimé: {filename}")
    except Exception as e:
        logging.error(f"Erreur lors du nettoyage des anciens fichiers: {e}")


def continuous_collection():
    """Collecte continue des données."""
    initialize_data_collection()
    
    last_send_time = time.time()
    
    while True:
        try:
            # Vérifier la limite de stockage
            if is_storage_limit_reached():
                logging.warning("Limite de 200Mo atteinte, arrêt de la collecte")
                break
            
            # Sauvegarder les données initiales si pas encore fait
            if not initial_data_saved:
                save_initial_data()
            
            # Collecter et sauvegarder les données variables
            variable_data = collect_variable_data()
            if variable_data and "error" not in variable_data:
                filename = save_variable_data_to_file(variable_data)
                if filename:
                    logging.info(f"Données variables collectées et sauvegardées dans {filename}")
            
            # Envoyer les fichiers toutes les SEND_INTERVAL secondes
            current_time = time.time()
            if current_time - last_send_time >= SEND_INTERVAL:
                send_files_to_server()
                last_send_time = current_time
            
            time.sleep(COLLECTION_INTERVAL)  # Attendre l'intervalle de collecte
            
        except Exception as e:
            logging.error(f"Erreur dans la collecte continue: {e}")
            time.sleep(5)  # Attendre avant de réessayer
            
            
# 4. FONCTION DE DÉBOGAGE SPÉCIFIQUE POUR LA BATTERIE
def debug_battery():
    """Fonction de débogage pour la batterie."""
    print("=== DÉBOGAGE BATTERIE ===")
    
    try:
        import psutil
        battery = psutil.sensors_battery()
        print(f"psutil.sensors_battery() retourne: {battery}")
        
        if battery:
            print(f"Pourcentage: {battery.percent}")
            print(f"Branché: {battery.power_plugged}")
            print(f"Secondes restantes: {battery.secsleft}")
        else:
            print("Aucune batterie détectée par psutil")
            
    except Exception as e:
        print(f"Erreur psutil: {e}")
    
    # Test de la fonction personnalisée
    battery_info = get_battery_info()
    print(f"Fonction get_battery_info() retourne: {json.dumps(battery_info, indent=2, ensure_ascii=False)}")
    
            
# Point d'entrée principal
if __name__ == "__main__":
    try:
        # Initialisation
        initialize_data_collection()
        
        # Démarrer la collecte continue dans le thread principal
        continuous_collection()
        
    except KeyboardInterrupt:
        logging.info("Script arrêté par l'utilisateur")
        print("\nArrêt du script...")
        send_files_to_server()
    except Exception as e:
        logging.error(f"Erreur non gérée: {e}")
        sys.exit(1)
