import React, { useState, useCallback } from 'react';
import {
  View,
  StyleSheet,
  StatusBar,
} from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
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
    <AppBackground style={styles.backgroundWrapper}>
      <StatusBar
        barStyle={currentColors.statusBar}
        backgroundColor={theme.backgroundType === 'solid' ? currentColors.canvasBg : 'transparent'}
        translucent={theme.backgroundType !== 'solid'}
      />
      <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right']}>
        {/* Barra Lateral Desplegable Única (Drawer con todas las opciones) */}
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

            {activeScreen === 'settings' && (
              <SettingsScreen
                onOpenDrawer={() => setIsDrawerOpen(true)}
              />
            )}
          </View>
        </View>
      </SafeAreaView>
    </AppBackground>
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
});
