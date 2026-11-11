#include "../host-manager.cpp"
#include <cassert>
#include <iostream>

int main() {
  const std::string nested = "com.tencent.mm.service.ProcessService$ExDeviceProcessService";
  assert(!valid_package(nested));
  assert(valid_component(nested));
  assert(valid_package("com.tencent.mm"));
  assert(valid_component("com.tencent.mm.ui.LauncherUI"));
  assert(valid_component("com.tencent.mm.service.ProcessService$Outer$Inner"));
  assert(valid_component("com.example._Receiver"));
  assert(valid_component("com.example.Outer$1"));
  for (const std::string name : {"", ".com.example.Service", "com..example.Service",
                                 "com.example.Service.", "com.example.1Service",
                                 "com.example/Service", "com.example.Service;echo",
                                 "com.example.Service\n", "com.example.Service:process"}) {
    assert(!valid_component(name));
  }
  assert(!valid_package("com.example$invalid"));
  std::cout << "COMPONENT_IDENTITY=passed|nested_classes=true|package_rules_preserved=true\n";
}
