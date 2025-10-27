import { CssBaseline, ThemeProvider, createTheme, Container, Box, Typography } from '@mui/material';

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#4f46e5',
    },
    background: {
      default: '#0f172a',
      paper: '#1e293b',
    },
  },
});

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Container maxWidth="lg">
        <Box sx={{ py: 8 }}>
          <Typography variant="h3" gutterBottom>
            TwinOps Admin Portal
          </Typography>
          <Typography variant="body1" color="text.secondary">
            Manage digital twins, review knowledge assets, and monitor workflow execution from this dashboard.
          </Typography>
        </Box>
      </Container>
    </ThemeProvider>
  );
}

export default App;
