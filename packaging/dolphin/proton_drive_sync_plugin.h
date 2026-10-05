/*
    SPDX-FileCopyrightText: 2026 Proton Drive Sync contributors
    SPDX-License-Identifier: MIT
*/

#ifndef PROTON_DRIVE_SYNC_PLUGIN_H
#define PROTON_DRIVE_SYNC_PLUGIN_H

#include <Dolphin/KVersionControlPlugin>

#include <QHash>
#include <QList>
#include <QString>
#include <QVariant>

class QAction;
class KFileItem;
class KFileItemList;

// Reads org.protondrivesync.FileStatus. A missing bus leaves every file unmarked.
class ProtonDriveSyncPlugin : public KVersionControlPlugin
{
    Q_OBJECT

public:
    ProtonDriveSyncPlugin(QObject *parent, const QList<QVariant> &args);

    QString fileName() const override;
    bool beginRetrieval(const QString &directory) override;
    void endRetrieval() override;
    ItemVersion itemVersion(const KFileItem &item) const override;
    QList<QAction *> versionControlActions(const KFileItemList &items) const override;
    QList<QAction *> outOfVersionControlActions(const KFileItemList &items) const override;

private:
    QHash<QString, ItemVersion> m_versions;
};

#endif
