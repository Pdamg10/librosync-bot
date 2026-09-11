import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  StatusBar,
} from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { useResponsive } from './src/hooks/useResponsive';
import { LibraryScreen } from './src/screens/LibraryScreen';
import { TelegramScreen } from './src/screens/TelegramScreen';
import { SettingsScreen } from './src/screens/SettingsScreen';
import { ChatScreen } from './src/screens/ChatScreen';
import { CustomizeScreen } from './src/screens/CustomizeScreen';
import { BuddyReadScreen } from './src/screens/BuddyReadScreen';
import { SidebarDrawer } from './src/components/SidebarDrawer';
import { AppBackground } from './src/components/AppBackground';
import { ThemeProvider, useAppTheme } from './src/theme/ThemeContext';
import { ShelfSummary, Book, TelegramLink } from './src/types';

type ScreenType = 'library' | 'chat' | 'customize' | 'buddy' | 'telegram' | 'settings';

function MainApp() {
  const { theme } = useAppTheme();
  const currentColors = theme.colors;

  const [activeScreen, setActiveScreen] = useState<ScreenType>('library');
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false);

  // Chat / Grupo activo de Telegram para aislamiento de biblioteca
  const [activeTelegramLink, setActiveTelegramLink] = useState<TelegramLink | null>(null);

  // Datos compartidos de biblioteca para la barra lateral y el chat
  const [shelves, setShelves] = useState<ShelfSummary | null>(null);
  const [totalBooks, setTotalBooks] = useState<number>(0);
  const [catalogBooks, setCatalogBooks] = useState<Book[]>([]);

  // Subpestañas para LibraryScreen
  const [libraryInitialTab, setLibraryInitialTab] = useState<'catalog' | 'shelves' | 'buddy'>('catalog');
  const [libraryInitialShelf, setLibraryInitialShelf] = useState<'reading' | 'favorites' | 'to_read' | 'finished'>('reading');

  const { isTablet } = useResponsive();

  const handleShelvesLoaded = useCallback((fetchedShelves: ShelfSummary | null, count: number, books: Book[]) => {
    setShelves(fetchedShelves);
    setTotalBooks(count);
    setCatalogBooks(books);
  }, []);

  const handleDrawerNavigate = (screen: string, subParam?: string) => {
    if (screen === 'library') {
      if (subParam === 'catalog') {
        setLibraryInitialTab('catalog');
      } else if (subParam === 'buddy') {
        setActiveScreen('buddy');
        return;
      } else if (subParam && subParam.startsWith('shelves:')) {
        setLibraryInitialTab('shelves');
        setLibraryInitialShelf(subParam.split(':')[1] as any);
      }
      setActiveScreen('library');
    } else if (screen === 'buddy') {
      setActiveScreen('buddy');
    } else if (screen === 'chat') {
      setActiveScreen('chat');
    } else if (screen === 'customize') {
      setActiveScreen('customize');
    } else if (screen === 'telegram') {
      setActiveScreen('telegram');
    } else if (screen === 'settings') {
      setActiveScreen('settings');
    }
  };

  return (
    <SafeAreaView style={[styles.safeArea, { backgroundColor: currentColors.canvasBg }]} edges={['top', 'left', 'right']}>
      <StatusBar barStyle={currentColors.statusBar} backgroundColor={currentColors.canvasBg} />

      <AppBackground style={styles.backgroundWrapper}>
        {/* Barra Lateral Desplegable (Drawer) */}
        <SidebarDrawer
          isOpen={isDrawerOpen}
          onClose={() => setIsDrawerOpen(false)}
          activeScreen={activeScreen}
          onNavigate={handleDrawerNavigate}
          shelves={shelves}
          totalBooksCount={totalBooks}
          groupTitle={activeTelegramLink ? activeTelegramLink.chat_title : '💋😜Club de lectura📖❤️'}
          userName="Lector LibroSync"
        />

        <View style={styles.mainLayout}>
          {/* Rail lateral vertical para Tablets (Inspirado en la imagen de referencia) */}
          {isTablet && (
            <View style={[styles.tabletIconRail, { backgroundColor: currentColors.cardBg, borderColor: currentColors.cardBorder }]}>
              <TouchableOpacity
                style={[styles.railAvatarBtn, { backgroundColor: currentColors.cardSecondaryBg, borderColor: currentColors.cardBorder }]}
                onPress={() => setIsDrawerOpen(true)}
              >
                <Text style={styles.railAvatarEmoji}>👩‍🌾</Text>
              </TouchableOpacity>

              <View style={styles.railIconsGroup}>
                <TouchableOpacity
                  style={[
                    styles.railIconBtn,
                    activeScreen === 'library' && [styles.railIconBtnActive, { backgroundColor: currentColors.cardSecondaryBg }],
                  ]}
                  onPress={() => {
                    setLibraryInitialTab('catalog');
                    setActiveScreen('library');
                  }}
                >
                  <Text style={styles.railIcon}>📚</Text>
                </TouchableOpacity>

                <TouchableOpacity
                  style={styles.railIconBtn}
                  onPress={() => {
                    setLibraryInitialTab('shelves');
                    setLibraryInitialShelf('favorites');
                    setActiveScreen('library');
                  }}
                >
                  <Text style={styles.railIcon}>⭐</Text>
                </TouchableOpacity>

                <TouchableOpacity
                  style={styles.railIconBtn}
                  onPress={() => {
                    setLibraryInitialTab('shelves');
                    setLibraryInitialShelf('reading');
                    setActiveScreen('library');
                  }}
                >
                  <Text style={styles.railIcon}>📖</Text>
                </TouchableOpacity>

                <TouchableOpacity
                  style={[
                    styles.railIconBtn,
                    activeScreen === 'chat' && [styles.railIconBtnActive, { backgroundColor: currentColors.cardSecondaryBg }],
                  ]}
                  onPress={() => setActiveScreen('chat')}
                >
                  <Text style={styles.railIcon}>💬</Text>
                </TouchableOpacity>

                <TouchableOpacity
                  style={[
                    styles.railIconBtn,
                    activeScreen === 'buddy' && [styles.railIconBtnActive, { backgroundColor: currentColors.cardSecondaryBg }],
                  ]}
                  onPress={() => setActiveScreen('buddy')}
                >
                  <Text style={styles.railIcon}>👥</Text>
                </TouchableOpacity>

                <TouchableOpacity
                  style={[
                    styles.railIconBtn,
                    activeScreen === 'customize' && [styles.railIconBtnActive, { backgroundColor: currentColors.cardSecondaryBg }],
                  ]}
                  onPress={() => setActiveScreen('customize')}
                >
                  <Text style={styles.railIcon}>🎨</Text>
                </TouchableOpacity>
              </View>

              <TouchableOpacity
                style={[styles.railSubscribePill, { backgroundColor: '#3B5B75' }]}
                onPress={() => setIsDrawerOpen(true)}
              >
                <Text style={styles.railSubscribeBell}>🔔</Text>
                <Text style={styles.railSubscribeText}>Club</Text>
              </TouchableOpacity>
            </View>
          )}

          {/* Contenido Principal de Pantallas */}
          <View style={styles.content}>
            {activeScreen === 'library' && (
              <LibraryScreen
                onOpenDrawer={() => setIsDrawerOpen(true)}
                onNavigateToChat={() => setActiveScreen('chat')}
                initialTab={libraryInitialTab}
                initialShelf={libraryInitialShelf}
                activeTelegramLinkId={activeTelegramLink?.id}
                onShelvesLoaded={handleShelvesLoaded}
              />
            )}

            {activeScreen === 'buddy' && (
              <BuddyReadScreen
                onOpenDrawer={() => setIsDrawerOpen(true)}
                groupTitle={activeTelegramLink ? activeTelegramLink.chat_title : '💋😜Club de lectura📖❤️'}
              />
            )}

            {activeScreen === 'chat' && (
              <ChatScreen
                onOpenDrawer={() => setIsDrawerOpen(true)}
                shelves={shelves}
                catalogBooks={catalogBooks}
              />
            )}

            {activeScreen === 'customize' && (
              <CustomizeScreen
                onOpenDrawer={() => setIsDrawerOpen(true)}
                onBack={() => setActiveScreen('library')}
              />
            )}

            {activeScreen === 'telegram' && (
              <TelegramScreen
                onOpenDrawer={() => setIsDrawerOpen(true)}
                activeLinkId={activeTelegramLink?.id}
                onSelectActiveLink={(link) => {
                  setActiveTelegramLink(link);
                  setActiveScreen('library');
                }}
              />
            )}
            {activeScreen === 'settings' && <SettingsScreen />}
          </View>
        </View>

        {/* Barra de Navegación Inferior para Teléfonos */}
        {!isTablet && (
          <View style={[styles.bottomNav, { backgroundColor: currentColors.cardBg, borderColor: currentColors.cardBorder }]}>
            <TouchableOpacity
              onPress={() => setIsDrawerOpen(true)}
              style={styles.navItem}
            >
              <Text style={styles.navIcon}>☰</Text>
              <Text style={[styles.navLabel, { color: currentColors.textSecondary }]}>Menú</Text>
            </TouchableOpacity>

            <TouchableOpacity
              onPress={() => {
                setLibraryInitialTab('catalog');
                setActiveScreen('library');
              }}
              style={[
                styles.navItem,
                activeScreen === 'library' && [styles.navItemActive, { backgroundColor: currentColors.cardSecondaryBg }],
              ]}
            >
              <Text style={styles.navIcon}>📖</Text>
              <Text
                style={[
                  styles.navLabel,
                  { color: currentColors.textSecondary },
                  activeScreen === 'library' && [styles.navLabelActive, { color: currentColors.textPrimary }],
                ]}
              >
                Catálogo
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              onPress={() => setActiveScreen('chat')}
              style={[
                styles.navItem,
                activeScreen === 'chat' && [styles.navItemActive, { backgroundColor: currentColors.cardSecondaryBg }],
              ]}
            >
              <Text style={styles.navIcon}>💬</Text>
              <Text
                style={[
                  styles.navLabel,
                  { color: currentColors.textSecondary },
                  activeScreen === 'chat' && [styles.navLabelActive, { color: currentColors.textPrimary }],
                ]}
              >
                Griffin AI
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              onPress={() => setActiveScreen('telegram')}
              style={[
                styles.navItem,
                activeScreen === 'telegram' && [styles.navItemActive, { backgroundColor: currentColors.cardSecondaryBg }],
              ]}
            >
              <Text style={styles.navIcon}>📱</Text>
              <Text
                style={[
                  styles.navLabel,
                  { color: currentColors.textSecondary },
                  activeScreen === 'telegram' && [styles.navLabelActive, { color: currentColors.textPrimary }],
                ]}
              >
                Telegram
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              onPress={() => setActiveScreen('settings')}
              style={[
                styles.navItem,
                activeScreen === 'settings' && [styles.navItemActive, { backgroundColor: currentColors.cardSecondaryBg }],
              ]}
            >
              <Text style={styles.navIcon}>⚙️</Text>
              <Text
                style={[
                  styles.navLabel,
                  { color: currentColors.textSecondary },
                  activeScreen === 'settings' && [styles.navLabelActive, { color: currentColors.textPrimary }],
                ]}
              >
                Ajustes
              </Text>
            </TouchableOpacity>
          </View>
        )}
      </AppBackground>
    </SafeAreaView>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <MainApp />
      </ThemeProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  backgroundWrapper: {
    flex: 1,
  },
  mainLayout: {
    flex: 1,
    flexDirection: 'row',
  },
  content: {
    flex: 1,
  },
  // Rail vertical de iconos para tablets (Estilo referencia)
  tabletIconRail: {
    width: 68,
    borderRightWidth: 1,
    alignItems: 'center',
    paddingVertical: 18,
    justifyContent: 'space-between',
  },
  railAvatarBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    borderWidth: 1.5,
    alignItems: 'center',
    justifyContent: 'center',
  },
  railAvatarEmoji: {
    fontSize: 22,
  },
  railIconsGroup: {
    gap: 16,
    alignItems: 'center',
  },
  railIconBtn: {
    width: 44,
    height: 44,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  railIconBtnActive: {
    borderWidth: 1,
  },
  railIcon: {
    fontSize: 20,
  },
  railSubscribePill: {
    paddingVertical: 12,
    paddingHorizontal: 8,
    borderRadius: 14,
    alignItems: 'center',
    width: 48,
  },
  railSubscribeBell: {
    fontSize: 16,
    marginBottom: 2,
  },
  railSubscribeText: {
    fontSize: 9,
    fontWeight: '800',
    color: '#FFFFFF',
    textTransform: 'uppercase',
  },
  bottomNav: {
    flexDirection: 'row',
    borderTopWidth: 1,
    paddingVertical: 8,
    paddingBottom: 12,
    justifyContent: 'space-around',
    shadowColor: '#2C221E',
    shadowOffset: { width: 0, height: -2 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 4,
  },
  navItem: {
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 10,
  },
  navItemActive: {},
  navIcon: {
    fontSize: 20,
    marginBottom: 3,
  },
  navLabel: {
    fontSize: 11,
    fontWeight: '600',
  },
  navLabelActive: {
    fontWeight: '700',
  },
});
