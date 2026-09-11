import React from 'react';
import { TouchableOpacity, Text, StyleSheet } from 'react-native';
import { colors, getGenreEmoji } from '../theme/colors';

interface GenreChipProps {
  genre: string;
  isSelected: boolean;
  onPress: () => void;
  count?: number;
}

export const GenreChip: React.FC<GenreChipProps> = ({
  genre,
  isSelected,
  onPress,
  count,
}) => {
  const emoji = getGenreEmoji(genre);
  const theme = colors.dark;

  return (
    <TouchableOpacity
      activeOpacity={0.7}
      onPress={onPress}
      style={[
        styles.chip,
        isSelected ? styles.chipSelected : styles.chipUnselected,
      ]}
    >
      <Text style={styles.emoji}>{emoji}</Text>
      <Text
        style={[
          styles.text,
          isSelected ? styles.textSelected : styles.textUnselected,
        ]}
      >
        {genre}
      </Text>
      {count !== undefined && count > 0 && (
        <Text
          style={[
            styles.badge,
            isSelected ? styles.badgeSelected : styles.badgeUnselected,
          ]}
        >
          {count}
        </Text>
      )}
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
    marginRight: 8,
    borderWidth: 1,
    shadowColor: '#3c2f2f',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  chipSelected: {
    backgroundColor: '#2C221E',
    borderColor: '#2C221E',
  },
  chipUnselected: {
    backgroundColor: '#FBF8F3',
    borderColor: '#DFD5C6',
  },
  emoji: {
    fontSize: 14,
    marginRight: 6,
  },
  text: {
    fontSize: 13,
    fontWeight: '600',
  },
  textSelected: {
    color: '#FBF8F3',
  },
  textUnselected: {
    color: '#7A6E65',
  },
  badge: {
    fontSize: 11,
    fontWeight: 'bold',
    marginLeft: 6,
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 10,
  },
  badgeSelected: {
    backgroundColor: 'rgba(255, 255, 255, 0.25)',
    color: '#FFFFFF',
  },
  badgeUnselected: {
    backgroundColor: '#EDE5D8',
    color: '#7A6E65',
  },
});
