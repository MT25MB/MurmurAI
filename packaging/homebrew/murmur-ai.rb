# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.47"
  sha256 "45E7200EB7BE1035E41F28009CBE82D4BB76D36B20071F2B5D440FB125B5FE69"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.47/Murmur.AI_1.2.47_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
