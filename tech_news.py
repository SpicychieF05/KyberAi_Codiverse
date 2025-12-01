"""
Tech News Fetcher Module
Fetches latest tech news from multiple sources
"""

import httpx
import asyncio
from datetime import datetime
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)


class TechNewsFetcher:
    """Fetches tech news from various sources"""
    
    def __init__(self):
        self.base_urls = {
            "hacker_news": "https://hacker-news.firebaseio.com/v0",
            "dev_to": "https://dev.to/api/articles",
            "github_trending": "https://api.github.com/search/repositories",
            "rapidapi": "https://api.rapidapi.com"
        }
        self.rapidapi_key = "c2dac7dddcmsh796784b7ed9e7bbp183a5bjsn0e747ab8ca77"
        self.rapidapi_headers = {
            "X-RapidAPI-Key": self.rapidapi_key,
            "X-RapidAPI-Host": "tech-news4.p.rapidapi.com"
        }
    
    async def get_hacker_news_top(self, count: int = 10) -> List[Dict]:
        """Fetch top stories from Hacker News"""
        try:
            async with httpx.AsyncClient() as client:
                # Get top story IDs
                response = await client.get(
                    f"{self.base_urls['hacker_news']}/topstories.json",
                    timeout=10.0
                )
                story_ids = response.json()[:count]
                
                # Fetch story details
                stories = []
                for story_id in story_ids:
                    story_response = await client.get(
                        f"{self.base_urls['hacker_news']}/item/{story_id}.json",
                        timeout=10.0
                    )
                    story = story_response.json()
                    if story:
                        stories.append({
                            "title": story.get("title", ""),
                            "url": story.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                            "score": story.get("score", 0),
                            "source": "Hacker News"
                        })
                
                return stories
        except Exception as e:
            logger.error(f"Error fetching Hacker News: {e}")
            return []
    
    async def get_dev_to_articles(self, tag: str = "coding", count: int = 10) -> List[Dict]:
        """Fetch trending articles from DEV.to"""
        try:
            async with httpx.AsyncClient() as client:
                params = {
                    "tag": tag,
                    "top": "7",  # Top articles from last 7 days
                    "per_page": count
                }
                response = await client.get(
                    self.base_urls["dev_to"],
                    params=params,
                    timeout=10.0
                )
                articles = response.json()
                
                return [{
                    "title": article.get("title", ""),
                    "url": article.get("url", ""),
                    "score": article.get("public_reactions_count", 0),
                    "source": "DEV.to",
                    "tags": article.get("tag_list", [])
                } for article in articles]
        except Exception as e:
            logger.error(f"Error fetching DEV.to articles: {e}")
            return []
    
    async def get_github_trending(self, language: str = "", count: int = 10) -> List[Dict]:
        """Fetch trending repositories from GitHub"""
        try:
            async with httpx.AsyncClient() as client:
                # Get repos created in last week, sorted by stars
                query = "stars:>100 created:>2024-11-24"
                if language:
                    query += f" language:{language}"
                
                params = {
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": count
                }
                
                response = await client.get(
                    self.base_urls["github_trending"],
                    params=params,
                    timeout=10.0
                )
                repos = response.json().get("items", [])
                
                return [{
                    "title": repo.get("full_name", ""),
                    "url": repo.get("html_url", ""),
                    "score": repo.get("stargazers_count", 0),
                    "source": "GitHub Trending",
                    "description": repo.get("description", ""),
                    "language": repo.get("language", "")
                } for repo in repos]
        except Exception as e:
            logger.error(f"Error fetching GitHub trending: {e}")
            return []
    
    async def get_rapidapi_news(self, topic: str = "technology", count: int = 10) -> List[Dict]:
        """Fetch tech news from RapidAPI"""
        try:
            async with httpx.AsyncClient() as client:
                # Using Tech News API from RapidAPI
                url = "https://tech-news4.p.rapidapi.com/news"
                params = {"topic": topic, "limit": count}
                
                response = await client.get(
                    url,
                    headers=self.rapidapi_headers,
                    params=params,
                    timeout=15.0
                )
                
                if response.status_code == 200:
                    articles = response.json()
                    news_list = []
                    
                    # Handle different response formats
                    if isinstance(articles, dict):
                        articles = articles.get("articles", articles.get("data", []))
                    
                    for article in articles[:count]:
                        if isinstance(article, dict):
                            news_list.append({
                                "title": article.get("title", article.get("headline", "")),
                                "url": article.get("url", article.get("link", "")),
                                "score": 0,
                                "source": article.get("source", "RapidAPI Tech News"),
                                "description": article.get("description", article.get("summary", ""))
                            })
                    
                    return news_list
                else:
                    logger.warning(f"RapidAPI returned status {response.status_code}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error fetching RapidAPI news: {e}")
            return []
    
    async def get_tech_news(self, category: str = "general", count: int = 10) -> List[Dict]:
        """
        Get tech news based on category
        
        Categories:
        - general: Top tech news from Hacker News
        - coding: Coding articles from DEV.to
        - github: Trending GitHub repositories
        - python/javascript/etc: Language-specific news
        """
        category = category.lower()
        
        if category in ["python", "javascript", "java", "go", "rust", "cpp", "csharp"]:
            # Language-specific: GitHub trending + DEV.to
            github_task = self.get_github_trending(category, count // 2)
            dev_task = self.get_dev_to_articles(category, count // 2)
            github_repos, dev_articles = await asyncio.gather(github_task, dev_task)
            return github_repos + dev_articles
        
        elif category == "coding":
            return await self.get_dev_to_articles("coding", count)
        
        elif category == "github":
            return await self.get_github_trending("", count)
        
        elif category == "rapidapi":
            return await self.get_rapidapi_news("technology", count)
        
        else:  # general - Mix Hacker News and RapidAPI
            hn_task = self.get_hacker_news_top(count // 2)
            rapid_task = self.get_rapidapi_news("technology", count // 2)
            hn_news, rapid_news = await asyncio.gather(hn_task, rapid_task)
            return hn_news + rapid_news
    
    def format_news_message(self, news_items: List[Dict], category: str = "Tech") -> str:
        """Format news items into a readable message"""
        if not news_items:
            return f"Sorry, I couldn't fetch {category} news at the moment. Please try again later."
        
        message = f"📰 **Top {len(news_items)} {category.title()} News**\n\n"
        
        for idx, item in enumerate(news_items, 1):
            title = item.get("title", "No title")
            url = item.get("url", "")
            source = item.get("source", "")
            score = item.get("score", 0)
            
            message += f"{idx}. **{title}**\n"
            if source:
                message += f"   📍 Source: {source}"
                if score > 0:
                    message += f" | ⭐ {score}"
                message += "\n"
            if url:
                message += f"   🔗 {url}\n"
            
            # Add description or tags if available
            if "description" in item and item["description"]:
                desc = item["description"][:100] + "..." if len(item["description"]) > 100 else item["description"]
                message += f"   💡 {desc}\n"
            elif "tags" in item and item["tags"]:
                message += f"   🏷️ Tags: {', '.join(item['tags'][:3])}\n"
            
            message += "\n"
        
        return message.strip()


# Global instance
tech_news_fetcher = TechNewsFetcher()
