#!/usr/bin/env python3

import asyncio
import base64
import json
import logging
import socket
import configparser
import sys
from datetime import datetime, timezone
from typing import Optional, Dict, Any

try:
    import websockets
except ImportError:
    sys.stderr.write("Error: websockets package not found. Install with: pip install websockets\n")
    sys.exit(1)

try:
    import aio_pika
except ImportError:
    sys.stderr.write("Error: aio-pika package not found. Install with: pip install aio-pika\n")
    sys.exit(1)

class KismetToQueue:
    def __init__(self, config_file: str = 'config.ini'):
        self.config = self._load_config(config_file)
        self.hostname = socket.gethostname()
        self.logger = self._setup_logging()
        self.rabbitmq_connection = None
        self.channel = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = self.config.getint('general', 'max_reconnect_attempts', fallback=10)
        self.reconnect_delay = self.config.getint('general', 'reconnect_delay', fallback=5)

    def _load_config(self, config_file: str) -> configparser.ConfigParser:
        config = configparser.ConfigParser()
        if not config.read(config_file):
            sys.stderr.write(f"Error: Could not read config file: {config_file}\n")
            sys.exit(1)
        self._validate_config(config)
        return config

    def _validate_config(self, config: configparser.ConfigParser) -> None:
        """Validate that all required config values are present."""
        required_fields = {
            'rabbitmq': ['username', 'password', 'host', 'port', 'virtual_host', 'exchange'],
            'kismet': ['host', 'port']
        }

        missing_fields = []
        for section, fields in required_fields.items():
            if not config.has_section(section):
                sys.stderr.write(f"Error: Missing required config section: [{section}]\n")
                sys.exit(1)

            for field in fields:
                if not config.has_option(section, field):
                    missing_fields.append(f"[{section}] {field}")

        if missing_fields:
            sys.stderr.write("Error: Missing required config fields:\n")
            for field in missing_fields:
                sys.stderr.write(f"  - {field}\n")
            sys.exit(1)

    def _setup_logging(self) -> logging.Logger:
        log_level = self.config.get('logging', 'level', fallback='INFO')
        log_format = self.config.get('logging', 'format', 
                                    fallback='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        logging.basicConfig(level=getattr(logging, log_level.upper()), format=log_format)
        return logging.getLogger(__name__)

    async def _connect_rabbitmq(self) -> bool:
        try:
            rabbitmq_url = "amqp://{username}:{password}@{host}:{port}/{vhost}".format(
                username=self.config.get('rabbitmq', 'username'),
                password=self.config.get('rabbitmq', 'password'),
                host=self.config.get('rabbitmq', 'host'),
                port=self.config.getint('rabbitmq', 'port'),
                vhost=self.config.get('rabbitmq', 'virtual_host')
            )

            self.rabbitmq_connection = await aio_pika.connect_robust(rabbitmq_url)
            self.channel = await self.rabbitmq_connection.channel()

            exchange_name = self.config.get('rabbitmq', 'exchange')
            exchange_type = self.config.get('rabbitmq', 'exchange_type', fallback='topic')

            self.exchange = await self.channel.declare_exchange(
                exchange_name,
                aio_pika.ExchangeType(exchange_type),
                durable=True
            )

            self.logger.info(f"Connected to RabbitMQ exchange: {exchange_name}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to connect to RabbitMQ: {e}")
            return False

    def _get_routing_key(self, message_data: Dict[str, Any]) -> str:
        message_type = message_data.get('message_type', 'unknown')
        device_type = message_data.get('device_data', {}).get('kismet_device_base_type', 'unknown')
        
        return f"kismet.{message_type}.{device_type}"

    async def _publish_to_rabbitmq(self, message_data: Dict[str, Any]) -> bool:
        try:
            if not self.channel or self.channel.is_closed:
                if not await self._connect_rabbitmq():
                    return False

            routing_key = self._get_routing_key(message_data)
            message_json = json.dumps(message_data, default=str)

            if self.exchange:
                await self.exchange.publish(
                    aio_pika.Message(
                        body=message_json.encode(),
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        content_type='application/json'
                    ),
                    routing_key=routing_key
                )
                self.logger.debug(f"Published message to {routing_key}: {message_json[:100]}...")
                return True
            else:
                self.logger.error("Exchange is not initialized, cannot publish message")
                return False

        except Exception as e:
            self.logger.error(f"Failed to publish message to RabbitMQ: {e}")
            return False

    def _format_message(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        
        message_data = {
            "hostname": self.hostname,
            "timestamp": timestamp,
            "source": "kismet",
            "raw_data": raw_data
        }
        
        if "kismet_device" in raw_data:
            message_data.update({
                "message_type": "device",
                "device_data": raw_data["kismet_device"]
            })
        elif "kismet_alert" in raw_data:
            message_data.update({
                "message_type": "alert",
                "device_data": raw_data["kismet_alert"]
            })
        elif "kismet_message" in raw_data:
            message_data.update({
                "message_type": "message",
                "device_data": raw_data["kismet_message"]
            })
        else:
            message_data.update({
                "message_type": "unknown",
                "device_data": raw_data
            })
        
        return message_data

    async def _kismet_websocket_handler(self, websocket):
        self.logger.info("Connected to Kismet WebSocket")
        self.reconnect_attempts = 0

        try:
            async for message in websocket:
                try:
                    raw_data = json.loads(message)
                    formatted_message = self._format_message(raw_data)

                    if not await self._publish_to_rabbitmq(formatted_message):
                        self.logger.error("Failed to publish message, continuing...")

                except json.JSONDecodeError as e:
                    self.logger.error(f"Failed to parse JSON message: {e}")
                except Exception as e:
                    self.logger.error(f"Error processing message: {e}")

        except websockets.exceptions.ConnectionClosed:
            self.logger.warning("Kismet WebSocket connection closed")
        except Exception as e:
            self.logger.error(f"Error in WebSocket handler: {e}")

    async def _connect_to_kismet(self):
        kismet_host = self.config.get('kismet', 'host')
        kismet_port = self.config.getint('kismet', 'port')
        kismet_username = self.config.get('kismet', 'username', fallback='')
        kismet_password = self.config.get('kismet', 'password', fallback='')
        kismet_api_key = self.config.get('kismet', 'api_key', fallback='')

        uri = f"ws://{kismet_host}:{kismet_port}/by-source/ws/events"

        headers = {}
        if kismet_api_key:
            headers["Authorization"] = f"Bearer {kismet_api_key}"
        elif kismet_username and kismet_password:
            credentials = base64.b64encode(f"{kismet_username}:{kismet_password}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"

        while self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                self.logger.info(f"Attempting to connect to Kismet at {uri} (attempt {self.reconnect_attempts + 1})")

                async with websockets.connect(uri, extra_headers=headers) as websocket:
                    await self._kismet_websocket_handler(websocket)

                # Connection closed normally - reset attempts and reconnect
                self.logger.info("WebSocket connection closed, reconnecting...")
                self.reconnect_attempts = 0
                await asyncio.sleep(self.reconnect_delay)

            except Exception as e:
                self.logger.error(f"Failed to connect to Kismet: {e}")
                self.reconnect_attempts += 1

                if self.reconnect_attempts < self.max_reconnect_attempts:
                    self.logger.info(f"Retrying in {self.reconnect_delay} seconds...")
                    await asyncio.sleep(self.reconnect_delay)
                else:
                    self.logger.error(f"Max reconnection attempts ({self.max_reconnect_attempts}) reached")
                    break

    async def cleanup(self):
        if self.rabbitmq_connection and not self.rabbitmq_connection.is_closed:
            await self.rabbitmq_connection.close()
            self.logger.info("RabbitMQ connection closed")

    async def run(self):
        if not await self._connect_rabbitmq():
            self.logger.error("Failed to establish initial RabbitMQ connection")
            return

        try:
            await self._connect_to_kismet()
        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal, shutting down...")
        finally:
            await self.cleanup()

def main():
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    else:
        config_file = 'config.ini'
    
    kismet_queue = KismetToQueue(config_file)
    
    try:
        asyncio.run(kismet_queue.run())
    except KeyboardInterrupt:
        print("\nShutting down...")

if __name__ == "__main__":
    main()