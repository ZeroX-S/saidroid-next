#include "base/mem_map.h"
#include "dex/dex_file_loader.h"
#include "dexlayout/dexlayout.h"

#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>

// Link against the same standalone ART libraries used to build boot images.
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    art::MemMap::Init();
    std::ifstream input(argv[1], std::ios::binary);
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(input)), {});
    if (bytes.size() < 128 || std::memcmp(bytes.data(), "cdex001", 7) != 0) return 3;
    const auto *header = reinterpret_cast<const art::DexFile::Header *>(bytes.data());
    if (header->file_size_ > bytes.size() || header->data_off_ > bytes.size()) return 4;

    const art::DexFileLoader loader;
    std::string error;
    // vdexExtractor has already unquickened these instructions. Compact DEX
    // shares its data section across files and requires the separate-data API.
    auto dex = loader.OpenWithDataSection(bytes.data(), header->file_size_,
            bytes.data() + header->data_off_, bytes.size() - header->data_off_,
            argv[1], header->checksum_, nullptr, false, false, &error);
    if (!dex) {
        std::fprintf(stderr, "%s\n", error.c_str());
        return 5;
    }
    art::Options options;
    options.build_dex_ir_ = true;
    options.output_dex_directory_ = argv[2];
    options.verify_output_ = true;
    art::DexLayout layout(options, nullptr, stdout, nullptr);
    if (!layout.ProcessDexFile(argv[1], dex.get(), 0, nullptr, &error)) {
        std::fprintf(stderr, "%s\n", error.c_str());
        return 6;
    }
    return 0;
}
