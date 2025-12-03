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
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("Groq API returned None content")
        return content

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
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("OpenRouter API returned None content")
        return content

class GeminiClient(ProviderClient):
    def __init__(self, api_key: str):
        try:
            import google.generativeai as genai  # type: ignore
            genai.configure(api_key=api_key)  # type: ignore
            super().__init__('gemini', api_key, '', 'gemini-2.0-flash-exp')
            self.genai_model = genai.GenerativeModel('gemini-2.0-flash-exp')  # type: ignore
        except (AttributeError, ImportError) as e:
            # Handle different package versions or missing package
            raise ImportError(f"Failed to initialize Gemini client: {e}")
    
    async def chat(self, message: str) -> str:
        self.call_history.append(time.time())
        response = await asyncio.to_thread(self.genai_model.generate_content, message)
        if not response.text:
            raise ValueError("Gemini API returned empty response")
        return response.text

class DeepSeekClient(ProviderClient):
    def __init__(self, api_key: str, base_url: str):
        super().__init__('deepseek', api_key, base_url, 'deepseek-chat')
    
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
            max_tokens=1000
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("DeepSeek API returned None content")
        return content

class MultiAPIClient:
    def __init__(self):
        # Initialize providers with keys from .env
        # Note: Using GOOGLE_API_KEY for Gemini as per existing .env
        self.providers = {}
        
        groq_key = os.getenv('GROQ_API_KEY')
        if groq_key:
            try:
                self.providers['groq'] = GroqClient(groq_key)
            except Exception as e:
                print(f"⚠️ Failed to initialize Groq: {e}")
            
        openrouter_key = os.getenv('OPENROUTER_API_KEY')
        if openrouter_key:
            models_str = os.getenv('OPENROUTER_MODELS', 'tngtech/deepseek-r1t2-chimera:free')
            models = [m.strip() for m in models_str.split(',')]
            for i, model in enumerate(models):
                try:
                    self.providers[f'openrouter_{i}'] = OpenRouterClient(openrouter_key, model)
                except Exception as e:
                    print(f"⚠️ Failed to initialize OpenRouter model {i}: {e}")
            
        google_key = os.getenv('GOOGLE_API_KEY')
        if google_key:
            try:
                self.providers['gemini'] = GeminiClient(google_key)
            except Exception as e:
                print(f"⚠️ Failed to initialize Gemini: {e}")

        deepseek_key = os.getenv('DEEPSEEK_API_KEY')
        if deepseek_key:
            try:
                base_url = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
                self.providers['deepseek'] = DeepSeekClient(deepseek_key, base_url)
            except Exception as e:
                print(f"⚠️ Failed to initialize DeepSeek: {e}")
            
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
        if 'deepseek' in self.providers:
            self.provider_order.append('deepseek')
        
        # Set RPM limits - use the same limit for all openrouter models
        self.rpm_limits = {}
        if 'groq' in self.providers:
            self.rpm_limits['groq'] = 50
        if 'gemini' in self.providers:
            self.rpm_limits['gemini'] = 12
        if 'deepseek' in self.providers:
            self.rpm_limits['deepseek'] = 50
        for p in openrouter_providers:
            self.rpm_limits[p] = 30
        
        self.session_context: Dict[str, Dict] = {}
        
        # Query complexity tier-based priority matrix
        # Build dynamic tier lists based on available providers
        available_openrouters = [p for p in self.providers.keys() if p.startswith('openrouter_')]
        
        # Simple: fast/light models for quick factual queries
        simple_tier = []
        if 'openrouter_1' in self.providers:
            simple_tier.append('openrouter_1')
        if 'openrouter_2' in self.providers:
            simple_tier.append('openrouter_2')
        if 'openrouter_0' in self.providers:
            simple_tier.append('openrouter_0')
        # Add any other openrouters not yet added
        for p in available_openrouters:
            if p not in simple_tier:
                simple_tier.append(p)
        if 'gemini' in self.providers:
            simple_tier.append('gemini')
        if 'deepseek' in self.providers:
            simple_tier.append('deepseek')
        if 'groq' in self.providers:
            simple_tier.append('groq')
        
        # Medium: balanced models for analysis/multi-step reasoning
        medium_tier = []
        if 'openrouter_0' in self.providers:
            medium_tier.append('openrouter_0')
        if 'gemini' in self.providers:
            medium_tier.append('gemini')
        if 'openrouter_1' in self.providers:
            medium_tier.append('openrouter_1')
        # Add remaining openrouters
        for p in available_openrouters:
            if p not in medium_tier:
                medium_tier.append(p)
        if 'groq' in self.providers:
            medium_tier.append('groq')
        if 'deepseek' in self.providers:
            medium_tier.append('deepseek')
        
        # Complex: premium models for detailed reasoning
        complex_tier = []
        if 'groq' in self.providers:
            complex_tier.append('groq')
        if 'gemini' in self.providers:
            complex_tier.append('gemini')
        if 'deepseek' in self.providers:
            complex_tier.append('deepseek')
        if 'openrouter_0' in self.providers:
            complex_tier.append('openrouter_0')
        if 'openrouter_2' in self.providers:
            complex_tier.append('openrouter_2')
        if 'openrouter_1' in self.providers:
            complex_tier.append('openrouter_1')
        # Add remaining openrouters
        for p in available_openrouters:
            if p not in complex_tier:
                complex_tier.append(p)
        
        self.tier_priorities = {
            'simple': simple_tier,
            'medium': medium_tier,
            'complex': complex_tier
        }
        
        # Validate that we have at least one provider
        if not self.providers:
            raise ValueError("No AI providers configured. Please check your .env file for API keys.")
    
    def classify_query(self, text: str) -> str:
        """Classify query complexity in ~50ms for intelligent routing"""
        text_lower = text.lower()
        word_count = len(text.split())
        
        # Complex: Check first for high-priority keywords regardless of length
        complex_keywords = ['analyze deeply', 'detailed plan', 'step-by-step reasoning', 
                           'pros and cons', 'comprehensive analysis', 'in-depth', 'elaborate',
                           'thorough explanation', 'detailed breakdown', 'critically evaluate',
                           'comprehensive', 'architecture', 'scalable', 'microservices']
        if any(keyword in text_lower for keyword in complex_keywords) or word_count > 50:
            return 'complex'
        
        # Medium: Check before simple to prioritize analytical keywords
        medium_keywords = ['explain', 'compare', 'how does', 'steps', 'list', 'describe',
                          'outline', 'summarize', 'analyze', 'why', 'how to', 'difference',
                          'what are', 'tell me about', 'show me', 'can you']
        if any(keyword in text_lower for keyword in medium_keywords):
            return 'medium'
        
        # Also medium if moderate length (15-50 words)
        if 15 <= word_count <= 50:
            return 'medium'
        
        # Simple: <15 words with basic keywords (greeting or simple fact)
        simple_keywords = ['what is', 'define', 'who is', 'when', 'where', 'time', 'date', 
                          'capital', 'yes', 'no', 'true', 'false', 'hi', 'hello', 'hey', 'thanks', 'thank you']
        if word_count < 15 and any(keyword in text_lower for keyword in simple_keywords):
            return 'simple'
        
        # Default: very short queries without keywords → simple
        if word_count < 10:
            return 'simple'
        
        # Safe fallback for everything else
        return 'medium'
        
    async def generate_response(self, session_id: str, message: str) -> Tuple[str, Optional[str]]:
        """Tier-based intelligent routing with failover logic"""
        prev_provider = self.session_context.get(session_id, {}).get('last_provider')
        
        # Classify query complexity (optimized ~50ms)
        start_classify = time.time()
        tier = self.classify_query(message)
        classify_time = (time.time() - start_classify) * 1000
        print(f"🔍 Query classified as '{tier}' in {classify_time:.1f}ms")
        
        # Get tier-specific priority list
        primary_priorities = self.tier_priorities.get(tier, self.provider_order)
        
        # Try primary tier providers
        result = await self._try_providers(primary_priorities, message, session_id, tier, prev_provider)
        if result:
            return result
        
        # Fallback to other tiers if primary tier exhausted
        print(f"⚠️ Tier '{tier}' exhausted, trying fallback tiers...")
        fallback_tiers = [t for t in ['simple', 'medium', 'complex'] if t != tier]
        
        for fallback_tier in fallback_tiers:
            fallback_priorities = self.tier_priorities.get(fallback_tier, [])
            result = await self._try_providers(fallback_priorities, message, session_id, 
                                              f"{tier}→{fallback_tier}", prev_provider)
            if result:
                return result
        
        # All providers failed across all tiers
        self.session_context[session_id] = {
            'status': 'all_exhausted', 
            'last_attempt': datetime.now().isoformat(),
            'failed_tier': tier
        }
        return "🤖 All AI services are temporarily busy. Please try again in 30 seconds!", None
    
    async def _try_providers(self, provider_list: List[str], message: str, 
                            session_id: str, tier_label: str, prev_provider: Optional[str]) -> Optional[Tuple[str, str]]:
        """Attempt to get response from list of providers"""
        if not provider_list:
            print(f"⚠️ No providers available in tier '{tier_label}'")
            return None
            
        for provider_name in provider_list:
            if provider_name not in self.providers:
                continue
            
            if provider_name not in self.rpm_limits:
                print(f"⚠️ No RPM limit configured for {provider_name}, skipping")
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
                    'last_tier': tier_label,
                    'switch_count': self.session_context[session_id].get('switch_count', 0) + (1 if prev_provider != provider_name else 0),
                    'last_used': datetime.now().isoformat()
                })
                
                await self._log_usage(provider_name, True, session_id, elapsed, tier_label)
                print(f"✅ {provider_name} [{tier_label}]: {elapsed:.2f}s")
                return response, provider_name
                
            except Exception as e:
                print(f"❌ {provider_name} failed: {str(e)[:50]}")
                await self._log_usage(provider_name, False, session_id, 0, tier_label)
                continue
        
        return None

    async def _log_usage(self, provider: str, success: bool, session_id: str, response_time: float, tier: str = 'unknown'):
        """Persistent logging with tier tracking"""
        try:
            async with aiosqlite.connect('api_stats.db') as db:
                # Check if tier column exists, add if not
                cursor = await db.execute("PRAGMA table_info(usage)")
                columns = [row[1] for row in await cursor.fetchall()]
                
                if 'tier' not in columns:
                    await db.execute("ALTER TABLE usage ADD COLUMN tier TEXT DEFAULT 'unknown'")
                    await db.commit()
                
                await db.execute(
                    "INSERT INTO usage (provider, success, session_id, response_time, tier) VALUES (?, ?, ?, ?, ?)",
                    (provider, int(success), session_id, response_time, tier)
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
