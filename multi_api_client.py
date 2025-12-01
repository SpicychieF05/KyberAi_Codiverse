import asyncio
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import httpx
from dotenv import load_dotenv
import os
import aiosqlite

load_dotenv()

class RateLimitError(Exception):
    pass

class ProviderClient:
    def __init__(self, name: str, api_key: str, base_url: str, model: str):
        self.name = name
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.call_history: List[float] = []  # timestamps

    async def chat(self, message: str) -> str:
        raise NotImplementedError

    def check_rate_limit(self, rpm: int, window: int = 60) -> bool:
        """Sliding window rate limit check"""
        now = time.time()
        self.call_history = [t for t in self.call_history if now - t < window]
        return len(self.call_history) < rpm

class GroqClient(ProviderClient):
    def __init__(self, api_key: str):
        super().__init__('groq', api_key, 'https://api.groq.com/openai/v1', 'llama-3.3-70b-versatile')
    
    async def chat(self, message: str) -> str:
        import groq
        client = groq.Groq(api_key=self.api_key)
        self.call_history.append(time.time())
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=self.model,
            messages=[{"role": "user", "content": message}],
            max_tokens=1000
        )
        return response.choices[0].message.content

class OpenRouterClient(ProviderClient):
    def __init__(self, api_key: str, model: str):
        super().__init__('openrouter', api_key, 'https://openrouter.ai/api/v1', model)
    
    async def chat(self, message: str) -> str:
        from openai import OpenAI
        client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )
        self.call_history.append(time.time())
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=self.model,
            messages=[{"role": "user", "content": message}],
            extra_headers={
                "HTTP-Referer": "https://codiverse-dev.vercel.app",
                "X-Title": "CodiverseBot",
            }
        )
        return response.choices[0].message.content

class GeminiClient(ProviderClient):
    def __init__(self, api_key: str):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        super().__init__('gemini', api_key, '', 'gemini-2.0-flash-exp')
        self.model = genai.GenerativeModel('gemini-2.0-flash-exp')
    
    async def chat(self, message: str) -> str:
        self.call_history.append(time.time())
        response = await asyncio.to_thread(self.model.generate_content, message)
        return response.text

class MultiAPIClient:
    def __init__(self):
        # Initialize providers with keys from .env
        # Note: Using GOOGLE_API_KEY for Gemini as per existing .env
        self.providers = {}
        
        if os.getenv('GROQ_API_KEY'):
            self.providers['groq'] = GroqClient(os.getenv('GROQ_API_KEY'))
            
        if os.getenv('OPENROUTER_API_KEY'):
            models_str = os.getenv('OPENROUTER_MODELS', 'tngtech/deepseek-r1t2-chimera:free')
            models = [m.strip() for m in models_str.split(',')]
            for i, model in enumerate(models):
                self.providers[f'openrouter_{i}'] = OpenRouterClient(os.getenv('OPENROUTER_API_KEY'), model)
            
        if os.getenv('GOOGLE_API_KEY'):
            self.providers['gemini'] = GeminiClient(os.getenv('GOOGLE_API_KEY'))
            
        self.provider_order = []
        # Add groq if available
        if 'groq' in self.providers:
            self.provider_order.append('groq')
        # Add all openrouter models
        openrouter_providers = [p for p in self.providers.keys() if p.startswith('openrouter_')]
        self.provider_order.extend(openrouter_providers)
        # Add gemini if available
        if 'gemini' in self.providers:
            self.provider_order.append('gemini')
        
        # Set RPM limits - use the same limit for all openrouter models
        self.rpm_limits = {'groq': 50, 'gemini': 12}
        for p in openrouter_providers:
            self.rpm_limits[p] = 30
        self.session_context: Dict[str, Dict] = {}
        
    async def generate_response(self, session_id: str, message: str) -> Tuple[str, Optional[str]]:
        """Main failover logic"""
        prev_provider = self.session_context.get(session_id, {}).get('last_provider')
        
        for provider_name in self.provider_order:
            if provider_name not in self.providers:
                continue
                
            provider = self.providers[provider_name]
            
            # Rate limit check
            if not provider.check_rate_limit(self.rpm_limits[provider_name]):
                print(f"⏳ {provider_name} rate limited")
                continue
            
            try:
                start_time = time.time()
                response = await provider.chat(message)
                elapsed = time.time() - start_time
                
                # Update session context
                self.session_context.setdefault(session_id, {})
                self.session_context[session_id].update({
                    'last_provider': provider_name,
                    'switch_count': self.session_context[session_id].get('switch_count', 0) + (1 if prev_provider != provider_name else 0),
                    'last_used': datetime.now().isoformat()
                })
                
                await self._log_usage(provider_name, True, session_id, elapsed)
                print(f"✅ {provider_name}: {elapsed:.2f}s")
                return response, provider_name
                
            except Exception as e:
                print(f"❌ {provider_name} failed: {str(e)[:50]}")
                await self._log_usage(provider_name, False, session_id, 0)
                continue
        
        # All providers failed
        self.session_context[session_id] = {'status': 'all_exhausted', 'last_attempt': datetime.now().isoformat()}
        return "🤖 All AI services are temporarily busy. Please try again in 30 seconds!", None

    async def _log_usage(self, provider: str, success: bool, session_id: str, response_time: float):
        """Persistent logging"""
        try:
            async with aiosqlite.connect('api_stats.db') as db:
                await db.execute(
                    "INSERT INTO usage (provider, success, session_id, response_time) VALUES (?, ?, ?, ?)",
                    (provider, int(success), session_id, response_time)
                )
                await db.commit()
                
                # Update session
                await db.execute(
                    "INSERT OR REPLACE INTO sessions (chat_id, last_provider, switch_count, status, last_used) VALUES (?, ?, ?, ?, ?)",
                    (session_id, self.session_context.get(session_id, {}).get('last_provider'), 
                     self.session_context[session_id].get('switch_count', 0), 'active', datetime.now())
                )
                await db.commit()
        except Exception as e:
            print(f"Logging error: {e}")
