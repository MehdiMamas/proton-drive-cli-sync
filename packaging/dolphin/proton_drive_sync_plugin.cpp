/*
    SPDX-FileCopyrightText: 2026 Proton Drive Sync contributors
    SPDX-License-Identifier: MIT
*/

#include "proton_drive_sync_plugin.h"

#include <KFileItem>
#include <KPluginFactory>

#include <QDBusArgument>
#include <QDBusConnection>
#include <QDBusInterface>
#include <QDBusMessage>
#include <QDir>
#include <QVariantMap>

K_PLUGIN_CLASS_WITH_JSON(ProtonDriveSyncPlugin, "protondrivesyncdolphinplugin.json")

namespace {

// Names are cloudstatus.EMBLEMS. An unknown name shows no overlay.
KVersionControlPlugin::ItemVersion versionForEmblem(const QString &emblem)
{
    if (emblem == QLatin1String("emblem-default")) {
        return KVersionControlPlugin::NormalVersion;
    }
    if (emblem == QLatin1String("emblem-synchronizing")) {
        return KVersionControlPlugin::UpdateRequiredVersion;
    }
    if (emblem == QLatin1String("emblem-important")) {
        return KVersionControlPlugin::ConflictingVersion;
    }
    return KVersionControlPlugin::UnversionedVersion;
}

}

ProtonDriveSyncPlugin::ProtonDriveSyncPlugin(QObject *parent, const QList<QVariant> &args)
    : KVersionControlPlugin(parent)
{
    Q_UNUSED(args)
}

QString ProtonDriveSyncPlugin::fileName() const
{
    return QStringLiteral("protondrivesync");
}

bool ProtonDriveSyncPlugin::beginRetrieval(const QString &directory)
{
    m_versions.clear();
    if (!QDBusConnection::sessionBus().isConnected()) {
        return true;
    }

    QDBusInterface bus(QStringLiteral("org.protondrivesync.CloudProviders"),
                       QStringLiteral("/org/protondrivesync/CloudProviders"),
                       QStringLiteral("org.protondrivesync.FileStatus"),
                       QDBusConnection::sessionBus());
    if (!bus.isValid()) {
        return true;
    }

    const QDBusMessage reply = bus.call(QStringLiteral("GetDirectoryStatus"), directory);
    if (reply.type() != QDBusMessage::ReplyMessage || reply.arguments().isEmpty()) {
        return true;
    }

    QMap<QString, QString> emblems;
    const QVariant value = reply.arguments().at(0);
    if (value.canConvert<QDBusArgument>()) {
        QDBusArgument argument = value.value<QDBusArgument>();
        argument >> emblems;
    } else {
        const QVariantMap variantMap = value.toMap();
        for (auto it = variantMap.cbegin(); it != variantMap.cend(); ++it) {
            emblems.insert(it.key(), it.value().toString());
        }
    }

    for (auto it = emblems.cbegin(); it != emblems.cend(); ++it) {
        m_versions.insert(QDir::cleanPath(it.key()), versionForEmblem(it.value()));
    }
    return true;
}

void ProtonDriveSyncPlugin::endRetrieval()
{
}

KVersionControlPlugin::ItemVersion ProtonDriveSyncPlugin::itemVersion(const KFileItem &item) const
{
    const auto it = m_versions.constFind(QDir::cleanPath(item.mostLocalUrl().toLocalFile()));
    if (it == m_versions.cend()) {
        return UnversionedVersion;
    }
    return it.value();
}

#include "proton_drive_sync_plugin.moc"
