"""
MADMIN Module Store Service

Fetches module registry from cloud and handles installation from GitHub.
"""
import json
import logging
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

import httpx
from pydantic import BaseModel

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# Registry URL - change to your GitHub raw URL
REGISTRY_URL = "https://raw.githubusercontent.com/EdoardoFiore/madmin-modules/main/modules.json"

# Cache settings
_registry_cache: Optional[Dict] = None
_cache_time: Optional[datetime] = None
CACHE_TTL = timedelta(minutes=30)


class ModuleAuthor(BaseModel):
    name: str
    email: Optional[str] = None
    url: Optional[str] = None


class StoreModule(BaseModel):
    """Module info from the store registry."""
    id: str
    name: str
    description: str
    version: str = "0.0.0"
    repository: str
    author: Optional[ModuleAuthor] = None
    category: str = "other"
    tags: List[str] = []
    icon: str = "puzzle"
    features: List[str] = []
    screenshots: List[str] = []
    requirements: Dict[str, Any] = {}
    stars: int = 0
    downloads: int = 0
    verified: bool = False
    changelog: Dict[str, str] = {}
    updated_at: Optional[str] = None


class ModuleStore:
    """
    Handles fetching available modules from registry
    and installing them from GitHub.
    """
    
    async def fetch_registry(self, force_refresh: bool = False) -> Dict:
        """
        Fetch the module registry from cloud.
        Uses cache to avoid frequent requests.
        """
        global _registry_cache, _cache_time
        
        # Check cache
        if not force_refresh and _registry_cache and _cache_time:
            if datetime.utcnow() - _cache_time < CACHE_TTL:
                return _registry_cache
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(REGISTRY_URL)
                response.raise_for_status()
                
                registry = response.json()
                _registry_cache = registry
                _cache_time = datetime.utcnow()
                
                logger.info(f"Fetched registry with {len(registry.get('modules', []))} modules")
                return registry
                
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch registry: {e}")
            # Return cached version if available
            if _registry_cache:
                return _registry_cache
            raise
    
    async def get_available_modules(self, force_refresh: bool = False) -> List[StoreModule]:
        """Get list of all available modules from registry."""
        registry = await self.fetch_registry(force_refresh=force_refresh)
        modules = []
        
        for mod_data in registry.get("modules", []):
            try:
                modules.append(StoreModule(**mod_data))
            except Exception as e:
                logger.warning(f"Failed to parse module {mod_data.get('id')}: {e}")
        
        return modules
    
    async def get_module_info(self, module_id: str) -> Optional[StoreModule]:
        """Get details for a specific module."""
        modules = await self.get_available_modules()
        for mod in modules:
            if mod.id == module_id:
                return mod
        return None
    
    async def download_from_github(
        self,
        repo_url: str,
        version: Optional[str] = None
    ) -> Path:
        """
        Download module from GitHub repository.
        
        Priority:
        1. Try to download release asset (module.zip) - this counts as download
        2. Fall back to git clone if no release asset exists
        
        Args:
            repo_url: GitHub repository URL
            version: Tag/version to download (default: latest)
        
        Returns:
            Path to downloaded module directory
        """
        import zipfile
        import httpx
        
        # Clean URL and extract owner/repo
        repo_url = repo_url.rstrip("/").rstrip(".git")
        parts = repo_url.split("/")
        owner, repo = parts[-2], parts[-1]
        
        # Create temp directory
        temp_dir = Path(tempfile.mkdtemp(prefix="madmin_module_"))
        
        # Normalize version
        if version and not version.startswith("v"):
            version = f"v{version}"
        
        # Try to download release asset first (this counts as download!)
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                # Get release info
                if version:
                    release_url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{version}"
                else:
                    release_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
                
                logger.info(f"Checking for release asset at {release_url}")
                response = await client.get(release_url)
                
                if response.status_code == 200:
                    release_data = response.json()
                    assets = release_data.get("assets", [])
                    
                    # Look for module.zip asset
                    zip_asset = None
                    for asset in assets:
                        if asset.get("name", "").endswith(".zip"):
                            zip_asset = asset
                            break
                    
                    if zip_asset:
                        # Download the ZIP asset (this is counted!)
                        download_url = zip_asset.get("browser_download_url")
                        logger.info(f"Downloading release asset: {download_url}")
                        
                        zip_response = await client.get(download_url, follow_redirects=True)
                        if zip_response.status_code == 200:
                            zip_path = temp_dir / "module.zip"
                            zip_path.write_bytes(zip_response.content)
                            
                            # Extract ZIP
                            module_path = temp_dir / "module"
                            with zipfile.ZipFile(zip_path, 'r') as zf:
                                zf.extractall(module_path)
                            
                            # Check if manifest exists (might be in subfolder)
                            if (module_path / "manifest.json").exists():
                                logger.info("Downloaded module from release asset")
                                return module_path
                            
                            # Check for single subfolder
                            subdirs = [d for d in module_path.iterdir() if d.is_dir()]
                            if len(subdirs) == 1 and (subdirs[0] / "manifest.json").exists():
                                logger.info("Downloaded module from release asset (with subfolder)")
                                return subdirs[0]
                        
        except Exception as e:
            logger.warning(f"Could not download release asset: {e}, falling back to git clone")
        
        # Fallback: git clone
        logger.info(f"Falling back to git clone for {repo_url}")
        
        clone_url = repo_url + ".git" if not repo_url.endswith(".git") else repo_url
        
        versions_to_try = []
        if version:
            versions_to_try.append(version)
            versions_to_try.append(version.lstrip("v"))
        else:
            versions_to_try.append(None)
        
        last_error = None
        
        for ver in versions_to_try:
            try:
                cmd = ["git", "clone", "--depth", "1"]
                if ver:
                    cmd.extend(["--branch", ver])
                cmd.extend([clone_url, str(temp_dir / "module")])
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                
                if result.returncode == 0:
                    module_path = temp_dir / "module"
                    if (module_path / "manifest.json").exists():
                        return module_path
                    else:
                        raise ValueError("Downloaded repository has no manifest.json")
                else:
                    last_error = RuntimeError(f"Git clone failed: {result.stderr}")
                    shutil.rmtree(temp_dir / "module", ignore_errors=True)
            except Exception as e:
                shutil.rmtree(temp_dir / "module", ignore_errors=True)
                last_error = e
        
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise last_error or RuntimeError("Download failed")
    
    async def install_module(
        self,
        module_id: str,
        version: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Install a module from the store.
        
        1. Fetch module info from registry
        2. Download from GitHub
        3. Copy to staging directory
        4. Return success status
        
        Note: Actual activation is done via existing module loader.
        """
        # Get module info
        module_info = await self.get_module_info(module_id)
        if not module_info:
            return {"success": False, "error": f"Module {module_id} not found in registry"}
        
        staging_dir = Path(settings.staging_dir)
        target_path = staging_dir / module_id
        
        # Check if already in staging - remove if exists to ensure fresh download
        if target_path.exists():
            try:
                shutil.rmtree(target_path)
                logger.info(f"Removed existing staging directory for {module_id}")
            except Exception as e:
                return {"success": False, "error": f"Failed to clean up staging for {module_id}: {e}"}
        
        try:
            # Download from GitHub
            download_path = await self.download_from_github(
                module_info.repository,
                version or f"v{module_info.version}" if module_info.version != "0.0.0" else None
            )
            
            # Move to staging
            shutil.move(str(download_path), str(target_path))
            
            logger.info(f"Module {module_id} downloaded to staging")
            
            return {
                "success": True,
                "message": f"Module {module_info.name} scaricato. Vai su Moduli per installarlo.",
                "module_id": module_id,
                "version": module_info.version
            }
            
        except Exception as e:
            logger.error(f"Failed to install module {module_id}: {e}")
            return {"success": False, "error": str(e)}
    
    async def check_updates(self, installed_modules: List[Dict], force_refresh: bool = False) -> List[Dict]:
        """
        Check for available updates for installed modules.
        
        Args:
            installed_modules: List of {id, version} dicts
            force_refresh: If true, bypass cache
        
        Returns:
            List of modules with available updates
        """
        updates = []
        available = await self.get_available_modules(force_refresh=force_refresh)
        
        available_map = {m.id: m for m in available}
        
        for installed in installed_modules:
            module_id = installed.get("id")
            current_version = installed.get("version", "0.0.0")
            
            if module_id in available_map:
                store_version = available_map[module_id].version
                
                # Simple version comparison (could use semver)
                if store_version > current_version:
                    updates.append({
                        "id": module_id,
                        "name": available_map[module_id].name,
                        "current_version": current_version,
                        "available_version": store_version,
                        "changelog": available_map[module_id].changelog
                    })
        
        return updates


# Singleton instance
module_store = ModuleStore()
