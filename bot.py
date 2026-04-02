#!/usr/bin/env python3
import asyncio
import logging
import os
import sys
import random
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict
from dataclasses import dataclass
from telethon import TelegramClient, events, Button
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.errors import (
    FloodWaitError, UserPrivacyRestrictedError, 
    UserNotMutualContactError, PeerFloodError
)
from prometheus_client import Counter, Gauge, start_http_server

# ==================== CONFIGURATION ====================
@dataclass
class Config:
    # FIXED: Added missing brackets and default fallback values
    API_ID: int = int(os.getenv('API_ID', 7526968149))
    API_HASH: str = os.getenv('API_HASH', 'V2A6Dagewdc')
    BOT_TOKEN: str = os.getenv('BOT_TOKEN', '8771281629:AAFFVq4_ucZ_B1VRNBEZdpDTxMbp4kxEwDs')
    CHANNEL_USERNAME: str = '@solidusaitech1'
    ADMIN_ID: int = 7526968149
    
    # ADVANCED ANTI-BAN: Increased delays to mimic human behavior
    MAX_HOURLY_INVITES: int = 30 
    MAX_DAILY_INVITES: int = 500
    MIN_DELAY: float = 15.0 # Higher delay = safer account
    MAX_DELAY: float = 45.0
    
    PUBLIC_GROUPS: List[str] = ['@beseda_robloxi', '@satfeedsub']
    MONITORING_PORT: int = int(os.getenv('PORT', 8000))

config = Config()

# ==================== LOGGING & METRICS ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

invites_total = Counter('telegram_invites_total', 'Total invites sent')
successful_invites = Counter('successful_invites_total', 'Successful invites')
failed_invites = Counter('failed_invites_total', 'Failed invites')

# ==================== DATABASE ====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('pro_bot.db', check_same_thread=False)
        self.init_tables()
    
    def init_tables(self):
        cursor = self.conn.cursor()
        cursor.executescript('''
        CREATE TABLE IF NOT EXISTS invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            status TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        ''')
        self.conn.commit()
    
    def log_invite(self, user_id: int, status: str):
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO invites (user_id, status) VALUES (?, ?)", (user_id, status))
        self.conn.commit()

db = Database()

# ==================== CORE BOT ====================
class ProfessionalMemberBot:
    def __init__(self):
        # We use a session name that stays persistent
        self.client = TelegramClient('pro_session', config.API_ID, config.API_HASH)
        self.hourly_invites = 0
        self.is_running = False
    
    async def start(self):
        await self.client.start(bot_token=config.BOT_TOKEN)
        
        # Start health check server for Render
        try:
            start_http_server(config.MONITORING_PORT)
        except:
            pass

        # Handlers
        self.client.add_event_handler(self.handle_start, events.NewMessage(pattern='/start'))
        self.client.add_event_handler(self.handle_run, events.NewMessage(pattern='/run'))
        self.client.add_event_handler(self.handle_stop, events.NewMessage(pattern='/stop'))
        logger.info("🤖 System Online & Monitoring...")

    async def harvest_members(self) -> List[int]:
        members = []
        for group in config.PUBLIC_GROUPS:
            try:
                entity = await self.client.get_entity(group)
                async for user in self.client.iter_participants(entity, limit=50):
                    if not user.bot and user.id not in members:
                        members.append(user.id)
            except: continue
        return members

    async def smart_invite(self, user_id: int) -> bool:
        if self.hourly_invites >= config.MAX_HOURLY_INVITES:
            logger.info("⚠️ Hourly limit reached. Sleeping.")
            return False
        
        try:
            await asyncio.sleep(random.uniform(config.MIN_DELAY, config.MAX_DELAY))
            await self.client(InviteToChannelRequest(config.CHANNEL_USERNAME, [user_id]))
            
            db.log_invite(user_id, 'success')
            successful_invites.inc()
            self.hourly_invites += 1
            return True
            
        except FloodWaitError as e:
            logger.warning(f"⏳ FloodWait: {e.seconds}s")
            await asyncio.sleep(e.seconds + 10)
            return False
        except PeerFloodError:
            logger.error("❌ PeerFloodError: Account is restricted from adding members. Stopping.")
            self.is_running = False
            return False
        except (UserPrivacyRestrictedError, UserNotMutualContactError):
            db.log_invite(user_id, 'privacy_restricted')
            return False
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            return False

    async def auto_add_loop(self):
        while self.is_running:
            candidates = await self.harvest_members()
            for uid in candidates:
                if not self.is_running: break
                await self.smart_invite(uid)
                # Extra cooldown between successful invites
                await asyncio.sleep(random.randint(30, 60))
            await asyncio.sleep(600) # 10 min break after a batch

    async def handle_start(self, event):
        if event.sender_id != config.ADMIN_ID: return
        await event.respond("🤖 **PRO SYSTEM READY**\n\nCommands:\n/run - Start Adding\n/stop - Pause System")

    async def handle_run(self, event):
        if event.sender_id != config.ADMIN_ID: return
        if not self.is_running:
            self.is_running = True
            asyncio.create_task(self.auto_add_loop())
            await event.respond("🚀 **System Live. Adding members...**")

    async def handle_stop(self, event):
        if event.sender_id == config.ADMIN_ID:
            self.is_running = False
            await event.respond("🛑 **System Stopped.**")

async def main():
    bot = ProfessionalMemberBot()
    await bot.start()
    await bot.client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
