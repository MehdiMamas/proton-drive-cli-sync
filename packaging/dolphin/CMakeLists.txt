cmake_minimum_required(VERSION 3.16)
project(protondrivesyncdolphinplugin VERSION 1.0.0)

set(QT_MIN_VERSION "6.5.0")
set(KF_MIN_VERSION "6.0.0")

find_package(ECM ${KF_MIN_VERSION} REQUIRED NO_MODULE)
set(CMAKE_MODULE_PATH ${ECM_MODULE_PATH})

include(KDEInstallDirs)
include(KDECMakeSettings)
include(KDECompilerSettings NO_POLICY_SCOPE)
include(FeatureSummary)

find_package(Qt6 ${QT_MIN_VERSION} REQUIRED COMPONENTS DBus)
find_package(KF6 ${KF_MIN_VERSION} REQUIRED COMPONENTS CoreAddons KIO)
find_package(DolphinVcs REQUIRED)

kcoreaddons_add_plugin(protondrivesyncdolphinplugin INSTALL_NAMESPACE "dolphin/vcs")

target_sources(protondrivesyncdolphinplugin PRIVATE
    proton_drive_sync_plugin.cpp
    proton_drive_sync_plugin.h
)

target_link_libraries(protondrivesyncdolphinplugin PRIVATE
    DolphinVcs
    Qt6::DBus
    KF6::CoreAddons
    KF6::KIOCore
)

feature_summary(WHAT ALL FATAL_ON_MISSING_REQUIRED_PACKAGES)
