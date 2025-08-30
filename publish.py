#!/usr/bin/env python
"""
Script to bump version, commit, build, and publish the package.

Usage:
    python publish.py [patch|minor|major]
    
    Default is 'patch' if no argument provided.
    
    For CalVer (YYYY.MM.PATCH) format:
    - 'patch': Increments the patch version (e.g., 2025.8.0 -> 2025.8.1)
    - 'minor': Updates to current month (e.g., 2025.8.0 -> 2025.11.0)
    - 'major': Updates to current year and month (e.g., 2025.8.0 -> 2025.11.0)
"""

import re
import sys
import subprocess
from datetime import datetime
from pathlib import Path
import shutil


def get_current_version(pyproject_path):
    """Extract current version from pyproject.toml."""
    content = pyproject_path.read_text()
    match = re.search(r'^version = "(.+)"', content, re.MULTILINE)
    if not match:
        raise ValueError("Could not find version in pyproject.toml")
    return match.group(1)


def bump_version(current_version, bump_type="patch"):
    """
    Bump version using CalVer format: YYYY.MM.PATCH
    """
    parts = current_version.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid version format: {current_version}")
    
    year = int(parts[0])
    month = int(parts[1])
    patch = int(parts[2])
    
    now = datetime.now()
    current_year = now.year
    current_month = now.month
    
    if bump_type == "major" or bump_type == "minor":
        # Both major and minor update to current year.month
        new_year = current_year
        new_month = current_month
        
        # If we're already at current year.month, increment patch
        if year == new_year and month == new_month:
            new_patch = patch + 1
        else:
            new_patch = 0
    elif bump_type == "patch":
        # Keep same year.month, just increment patch
        new_year = year
        new_month = month
        new_patch = patch + 1
    else:
        raise ValueError(f"Invalid bump type: {bump_type}")
    
    return f"{new_year}.{new_month}.{new_patch}"


def update_version_in_file(file_path, old_version, new_version):
    """Update version string in a file."""
    content = file_path.read_text()
    updated_content = content.replace(f'version = "{old_version}"', f'version = "{new_version}"')
    
    if content == updated_content:
        print(f"⚠️  No version string found in {file_path}")
        return False
    
    file_path.write_text(updated_content)
    return True


def run_command(cmd, description, check=True):
    """Run a shell command and handle output."""
    print(f"\n📦 {description}...")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if check and result.returncode != 0:
        print(f"❌ Error: {description}")
        print(f"   stdout: {result.stdout}")
        print(f"   stderr: {result.stderr}")
        sys.exit(1)
    
    if result.stdout:
        print(f"   {result.stdout.strip()}")
    
    return result


def main():
    # Parse arguments
    bump_type = "patch"
    if len(sys.argv) > 1:
        bump_type = sys.argv[1].lower()
        if bump_type not in ["patch", "minor", "major"]:
            print(f"❌ Invalid bump type: {bump_type}")
            print("   Use: patch, minor, or major")
            sys.exit(1)
    
    # Setup paths
    root_dir = Path(__file__).parent
    pyproject_path = root_dir / "pyproject.toml"
    dist_dir = root_dir / "dist"
    
    print("🚀 Starting publish process...")
    print(f"   Bump type: {bump_type}")
    
    # Step 1: Get current version and bump it
    current_version = get_current_version(pyproject_path)
    new_version = bump_version(current_version, bump_type)
    
    print(f"\n📌 Version bump:")
    print(f"   Current: {current_version}")
    print(f"   New:     {new_version}")
    
    # Step 2: Update version in pyproject.toml
    if not update_version_in_file(pyproject_path, current_version, new_version):
        print("❌ Failed to update version in pyproject.toml")
        sys.exit(1)
    
    print(f"✅ Updated pyproject.toml")
    
    # Step 3: Check for uncommitted changes (excluding our version bump)
    result = run_command("git diff --stat --staged", "Checking for staged changes", check=False)
    if result.stdout.strip():
        print("⚠️  Warning: You have staged changes. They will be included in the version commit.")
        response = input("   Continue? (y/n): ")
        if response.lower() != 'y':
            # Revert version change
            update_version_in_file(pyproject_path, new_version, current_version)
            print("🔄 Reverted version change")
            sys.exit(0)
    
    # Step 4: Commit version bump
    run_command("git add pyproject.toml", "Staging version change")
    
    commit_message = f"Bump version to {new_version}"
    run_command(f'git commit -m "{commit_message}"', "Committing version change")
    
    # Step 5: Clean dist directory
    if dist_dir.exists():
        print(f"\n🗑️  Cleaning dist directory...")
        shutil.rmtree(dist_dir)
        print(f"   Removed {dist_dir}")
    
    dist_dir.mkdir(exist_ok=True)
    
    # Step 6: Build the package
    run_command("uv build", "Building package")
    
    # Step 7: Verify build artifacts
    wheel_files = list(dist_dir.glob("*.whl"))
    tar_files = list(dist_dir.glob("*.tar.gz"))
    
    if not wheel_files or not tar_files:
        print("❌ Build artifacts not found!")
        sys.exit(1)
    
    print(f"\n📦 Build artifacts:")
    for f in wheel_files + tar_files:
        size_kb = f.stat().st_size / 1024
        print(f"   {f.name} ({size_kb:.1f} KB)")
    
    # Step 8: Publish to PyPI
    print("\n🚀 Publishing to PyPI...")
    print("   This will upload to the real PyPI")
    response = input("   Continue? (y/n): ")
    
    if response.lower() != 'y':
        print("⚠️  Skipping publish. Package built but not uploaded.")
        print(f"   To publish manually: uv publish")
        sys.exit(0)
    
    run_command("uv publish", "Publishing to PyPI")
    
    # Step 9: Push to git
    print("\n📤 Pushing to git...")
    run_command("git push origin main", "Pushing to remote")
    
    # Step 10: Create git tag
    tag_name = f"v{new_version}"
    run_command(f'git tag -a {tag_name} -m "Release {new_version}"', f"Creating tag {tag_name}")
    run_command(f"git push origin {tag_name}", "Pushing tag")
    
    print(f"\n✅ Successfully published version {new_version}!")
    print(f"   Package: https://pypi.org/project/scopinator/{new_version}/")
    print(f"   Tag: {tag_name}")
    

if __name__ == "__main__":
    main()